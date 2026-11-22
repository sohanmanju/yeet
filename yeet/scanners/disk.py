"""Disk explorer for interactive filesystem navigation by size."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from time import monotonic

from ..models import SIZE_LOADING, DiskItem
from ..safety import BUILTIN_DANGEROUS_PATHS, matches_path


class DiskExplorer:
    """
    Explores disk directories by size with interactive navigation.

    Features:
    - Lazy loading of directory sizes
    - Caching for fast re-navigation
    - Minimum size filtering
    - Warning for dangerous system paths
    """

    DANGEROUS_PATHS = frozenset(str(path) for path in BUILTIN_DANGEROUS_PATHS)

    HIDDEN_SYSTEM_PATHS = frozenset(
        {
            "/dev",
            "/proc",
            "/sys",
            "/net",
            "/home",  # On macOS this is usually a symlink
            "/.vol",
            "/Volumes",  # Could be confusing with multiple volumes
        }
    )

    DEFAULT_MIN_SIZE = 5 * 1024 * 1024

    DEFAULT_CACHE_PATH = Path.home() / ".cache" / "yeet" / "sizes.json"

    MAX_CACHE_SIZE = 10000

    def __init__(
        self,
        min_size_bytes: int = DEFAULT_MIN_SIZE,
        ignored_paths: list[Path] | None = None,
    ) -> None:
        """
        Initialize the disk explorer.

        Args:
            min_size_bytes: Minimum size in bytes to show items (default 5 MB)
        """
        self.min_size_bytes = min_size_bytes
        self.ignored_paths = [
            path.expanduser().resolve() for path in ignored_paths or []
        ]

        self._size_cache: OrderedDict[str, int] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_generation = 0
        self._active_processes: list[subprocess.Popen] = []
        self._process_lock = threading.Lock()

    def scan_directory(
        self,
        path: Path,
        include_small: bool = False,
        *,
        on_update: Callable[[list[DiskItem], int], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[DiskItem]:
        """
        Scan a directory and return items sorted by size (largest first).

        Directories initially have size=SIZE_LOADING (-1) for lazy loading.
        Files get their size immediately.

        Args:
            path: Directory to scan
            include_small: If True, include items below min_size_bytes
            on_update: Optional batches and the number of directory entries
                still to read. Called from the scanning thread.
            stop_event: Stop enumeration when this scan is superseded.

        Returns:
            List of DiskItem sorted by size (largest first, loading items last)
        """
        items: list[DiskItem] = []

        if self._is_ignored(path):
            return items

        try:
            with os.scandir(path) as entries:
                entries = list(entries)
                if on_update is not None and entries:
                    on_update([], len(entries))
                last_update = monotonic()
                for index, entry in enumerate(entries):
                    if stop_event is not None and stop_event.is_set():
                        return items
                    try:
                        if self._is_ignored(Path(entry.path)):
                            continue

                        if self.is_hidden_system(Path(entry.path)):
                            continue

                        stat = entry.stat(follow_symlinks=False)
                        modified = datetime.fromtimestamp(stat.st_mtime)

                        if entry.is_dir(follow_symlinks=False):
                            cached_size = self.get_cached_size(Path(entry.path))
                            size = (
                                cached_size if cached_size is not None else SIZE_LOADING
                            )

                            if (
                                not include_small
                                and size != SIZE_LOADING
                                and size < self.min_size_bytes
                            ):
                                continue

                            items.append(
                                DiskItem(
                                    path=Path(entry.path),
                                    name=entry.name,
                                    size=size,
                                    is_dir=True,
                                    modified=modified,
                                    item_count=None,
                                )
                            )
                        elif entry.is_file(follow_symlinks=False):
                            size = stat.st_blocks * 512

                            if not include_small and size < self.min_size_bytes:
                                continue

                            items.append(
                                DiskItem(
                                    path=Path(entry.path),
                                    name=entry.name,
                                    size=size,
                                    is_dir=False,
                                    modified=modified,
                                    item_count=None,
                                )
                            )

                    except (OSError, PermissionError):
                        continue

                    if (
                        on_update is not None
                        and index + 1 < len(entries)
                        and ((index + 1) % 64 == 0 or monotonic() - last_update >= 0.05)
                    ):
                        on_update(list(items), len(entries) - index - 1)
                        last_update = monotonic()

        except (OSError, PermissionError):
            pass

        items.sort(
            key=lambda x: (
                x.size == SIZE_LOADING,
                -x.size if x.size != SIZE_LOADING else 0,
            )
        )

        if on_update is not None and not (
            stop_event is not None and stop_event.is_set()
        ):
            on_update(list(items), 0)

        return items

    def _is_ignored(self, path: Path) -> bool:
        """Check if a path should be skipped by the explorer."""
        if not self.ignored_paths:
            return False
        normalized = path.expanduser().resolve()
        for candidate in self.ignored_paths:
            if matches_path(normalized, candidate):
                return True
        return False

    def calculate_size(self, path: Path) -> int:
        """
        Calculate the total size of a path (file or directory).

        Uses the `du` command for directories (much faster than Python os.walk),
        and st_blocks for files to handle sparse files correctly.

        Results are cached for fast re-navigation.

        Args:
            path: Path to calculate size for

        Returns:
            Size in bytes (actual disk usage)
        """
        path_str = str(path)

        with self._cache_lock:
            generation = self._cache_generation
            if path_str in self._size_cache:
                self._size_cache.move_to_end(path_str)
                return self._size_cache[path_str]

        total = 0

        try:
            if path.is_file():
                stat = path.stat()

                # st_blocks is in 512-byte units
                total = stat.st_blocks * 512
            elif path.is_dir():
                # Note: du may return non-zero exit code due to permission errors
                # but still output the size, so we check stdout regardless
                proc = subprocess.Popen(
                    ["du", "-sk", path_str],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                with self._process_lock:
                    self._active_processes.append(proc)
                try:
                    stdout, _ = proc.communicate(timeout=60)
                    if stdout:
                        try:
                            size_kb = stdout.split()[0]
                            total = int(size_kb) * 1024
                        except (ValueError, IndexError):
                            pass
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    raise
                finally:
                    with self._process_lock:
                        if proc in self._active_processes:
                            self._active_processes.remove(proc)
        except (OSError, PermissionError, subprocess.TimeoutExpired, ValueError):
            pass

        with self._cache_lock:
            if generation == self._cache_generation:
                self._size_cache[path_str] = total
                self._size_cache.move_to_end(path_str)
                while len(self._size_cache) > self.MAX_CACHE_SIZE:
                    self._size_cache.popitem(last=False)
        return total

    def is_dangerous(self, path: Path) -> bool:
        """
        Check if a path is a system path that needs a warning before deletion.

        Args:
            path: Path to check

        Returns:
            True if path is dangerous
        """
        path_str = str(path)

        if path_str in self.DANGEROUS_PATHS:
            return True

        for dangerous in self.DANGEROUS_PATHS:
            if path_str.startswith(dangerous + "/"):
                # Only first level is dangerous
                # e.g., /Applications/Xcode.app is dangerous
                # but /Users/sohan/Applications is not
                remaining = path_str[len(dangerous) + 1 :]
                if "/" not in remaining:
                    return True

        return False

    def is_hidden_system(self, path: Path) -> bool:
        """
        Check if a path should be completely hidden from the explorer.

        Args:
            path: Path to check

        Returns:
            True if path should be hidden
        """
        path_str = str(path)

        for hidden in self.HIDDEN_SYSTEM_PATHS:
            if path_str == hidden or path_str.startswith(hidden + "/"):
                return True

        return False

    def clear_cache(self) -> None:
        """Clear the size cache."""
        with self._cache_lock:
            self._cache_generation += 1
            self._size_cache.clear()

    def kill_active_processes(self) -> int:
        """
        Kill all active du processes.

        Call this when shutting down to ensure clean exit.

        Returns:
            Number of processes killed
        """
        with self._cache_lock:
            self._cache_generation += 1
        killed = 0
        with self._process_lock:
            for proc in self._active_processes:
                try:
                    proc.terminate()
                    killed += 1
                except (OSError, ProcessLookupError):
                    pass
            self._active_processes.clear()
        return killed

    def get_cached_size(self, path: Path) -> int | None:
        """
        Get cached size for a path, or None if not cached.

        Args:
            path: Path to look up

        Returns:
            Cached size in bytes, or None
        """
        with self._cache_lock:
            return self._size_cache.get(str(path))

    def save_cache(self, cache_path: Path | None = None) -> bool:
        """
        Save the size cache to disk.

        Args:
            cache_path: Path to save cache to (default: ~/.cache/yeet/sizes.json)

        Returns:
            True on success, False on failure
        """
        if cache_path is None:
            cache_path = self.DEFAULT_CACHE_PATH

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            with self._cache_lock:
                cache_data = {
                    "version": 1,
                    "timestamp": datetime.now().isoformat(),
                    "sizes": dict(self._size_cache),
                }

            with open(cache_path, "w") as f:
                json.dump(cache_data, f)

            return True
        except (OSError, PermissionError, TypeError):
            return False

    def load_cache(
        self, cache_path: Path | None = None, max_age_hours: int = 24
    ) -> int:
        """
        Load the size cache from disk.

        Args:
            cache_path: Path to load cache from (default: ~/.cache/yeet/sizes.json)
            max_age_hours: Skip entries older than this many hours

        Returns:
            Count of entries loaded
        """
        if cache_path is None:
            cache_path = self.DEFAULT_CACHE_PATH

        with self._cache_lock:
            generation = self._cache_generation
        try:
            if not cache_path.exists():
                return 0

            with open(cache_path, "r") as f:
                cache_data = json.load(f)

            if not isinstance(cache_data, dict):
                return 0
            if "sizes" not in cache_data or not isinstance(cache_data["sizes"], dict):
                return 0

            timestamp_str = cache_data.get("timestamp")
            if timestamp_str:
                try:
                    cache_time = datetime.fromisoformat(timestamp_str)
                    age_hours = (datetime.now() - cache_time).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        return 0
                except (ValueError, TypeError):
                    pass

            loaded = {}
            for path_str, size in cache_data["sizes"].items():
                if not isinstance(size, int):
                    continue

                try:
                    path = Path(path_str)
                    if not path.exists():
                        continue

                    loaded[path_str] = size
                except (OSError, PermissionError):
                    continue

            with self._cache_lock:
                if generation != self._cache_generation:
                    return 0
                self._size_cache.update(loaded)
                while len(self._size_cache) > self.MAX_CACHE_SIZE:
                    self._size_cache.popitem(last=False)
            return len(loaded)
        except (OSError, PermissionError, json.JSONDecodeError, TypeError):
            return 0

    def invalidate_cache(self, path: Path) -> None:
        """
        Invalidate a changed path, its descendants, and ancestor totals.

        Args:
            path: Path to invalidate
        """
        path_str = str(path)
        path_prefix = path_str + "/"

        with self._cache_lock:
            self._cache_generation += 1
            keys_to_remove = [
                key
                for key in self._size_cache
                if key == path_str
                or key.startswith(path_prefix)
                or Path(key) in path.parents
            ]
            for key in keys_to_remove:
                del self._size_cache[key]

    def calculate_sizes_parallel(
        self,
        paths: list[Path],
        callback: Callable[[Path, int], None] | None = None,
        max_workers: int = 4,
        stop_event: threading.Event | None = None,
    ) -> dict[Path, int]:
        """
        Calculate sizes for multiple paths in parallel using a thread pool.

        Uses ThreadPoolExecutor to calculate sizes concurrently, which can
        significantly speed up size calculation for many directories.

        Args:
            paths: List of paths to calculate sizes for
            callback: Optional callback called with (path, size) as each completes
            max_workers: Maximum number of worker threads (default 4)
            stop_event: Optional threading.Event to signal early termination

        Returns:
            Dict mapping each path to its calculated size
        """
        results: dict[Path, int] = {}

        if not paths:
            return results

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_path = {
                executor.submit(self.calculate_size, path): path for path in paths
            }

            for future in as_completed(future_to_path):
                if stop_event is not None and stop_event.is_set():
                    for f in future_to_path:
                        f.cancel()
                    break

                path = future_to_path[future]
                try:
                    size = future.result()
                    results[path] = size
                    if callback is not None:
                        callback(path, size)
                except Exception as e:
                    logging.debug(f"Error calculating size for {path}: {e}")

                    results[path] = 0
                    if callback is not None:
                        callback(path, 0)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return results

    def calculate_sizes_prioritized(
        self,
        paths: list[Path],
        priority_paths: list[Path],
        callback: Callable[[Path, int], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> dict[Path, int]:
        """
        Calculate sizes with priority paths processed first.

        This method calculates sizes for priority_paths first (typically visible
        items in the UI), then calculates the remaining paths. This allows the
        UI to show sizes for visible items as quickly as possible.

        Args:
            paths: All paths that need size calculation
            priority_paths: Subset of paths to calculate first (visible items)
            callback: Optional callback called with (path, size) as each completes
            stop_event: Optional threading.Event to signal early termination

        Returns:
            Dict mapping each path to its calculated size
        """
        results: dict[Path, int] = {}

        all_paths_set = set(paths)
        priority_set = set(priority_paths)

        priority_to_process = [p for p in priority_paths if p in all_paths_set]

        remaining_paths = [p for p in paths if p not in priority_set]

        if priority_to_process:
            if stop_event is not None and stop_event.is_set():
                return results
            priority_results = self.calculate_sizes_parallel(
                priority_to_process, callback=callback, stop_event=stop_event
            )
            results.update(priority_results)

        if remaining_paths:
            if stop_event is not None and stop_event.is_set():
                return results
            remaining_results = self.calculate_sizes_parallel(
                remaining_paths, callback=callback, stop_event=stop_event
            )
            results.update(remaining_results)

        return results
