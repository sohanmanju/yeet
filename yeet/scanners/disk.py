"""Disk explorer for interactive filesystem navigation by size."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import DiskItem, SIZE_LOADING


class DiskExplorer:
    """
    Explores disk directories by size with interactive navigation.

    Features:
    - Lazy loading of directory sizes
    - Caching for fast re-navigation
    - Minimum size filtering
    - Warning for dangerous system paths
    """

    # Paths that should trigger a warning before deletion
    DANGEROUS_PATHS = frozenset(
        {
            "/System",
            "/usr",
            "/bin",
            "/sbin",
            "/var",
            "/etc",
            "/Applications",
            "/Library",
            "/private",
            "/Users/Shared",
            "/.Spotlight-V100",
            "/.fseventsd",
            "/cores",
            "/opt",
        }
    )

    # Paths to completely hide (not useful for cleanup)
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

    # Default minimum size: 5 MB
    DEFAULT_MIN_SIZE = 5 * 1024 * 1024

    # Default cache file path
    DEFAULT_CACHE_PATH = Path.home() / ".cache" / "yeet" / "sizes.json"

    # Maximum number of entries in size cache (LRU eviction)
    MAX_CACHE_SIZE = 10000

    def __init__(self, min_size_bytes: int = DEFAULT_MIN_SIZE) -> None:
        """
        Initialize the disk explorer.

        Args:
            min_size_bytes: Minimum size in bytes to show items (default 5 MB)
        """
        self.min_size_bytes = min_size_bytes
        # Use OrderedDict for LRU cache behavior
        self._size_cache: OrderedDict[str, int] = OrderedDict()
        self._active_processes: list[subprocess.Popen] = []
        self._process_lock = threading.Lock()

    def scan_directory(
        self,
        path: Path,
        include_small: bool = False,
    ) -> list[DiskItem]:
        """
        Scan a directory and return items sorted by size (largest first).

        Directories initially have size=SIZE_LOADING (-1) for lazy loading.
        Files get their size immediately.

        Args:
            path: Directory to scan
            include_small: If True, include items below min_size_bytes

        Returns:
            List of DiskItem sorted by size (largest first, loading items last)
        """
        items: list[DiskItem] = []

        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        # Skip hidden system paths
                        if self.is_hidden_system(Path(entry.path)):
                            continue

                        stat = entry.stat(follow_symlinks=False)
                        modified = datetime.fromtimestamp(stat.st_mtime)

                        if entry.is_dir(follow_symlinks=False):
                            # Check cache first
                            cached_size = self._size_cache.get(entry.path)
                            size = (
                                cached_size if cached_size is not None else SIZE_LOADING
                            )

                            # Skip small directories if we know their size
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
                            # Use st_blocks for actual disk usage (handles sparse files)
                            size = stat.st_blocks * 512

                            # Skip small files
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

        except (OSError, PermissionError):
            pass

        # Sort: known sizes first (largest to smallest), then loading items
        items.sort(
            key=lambda x: (
                x.size == SIZE_LOADING,
                -x.size if x.size != SIZE_LOADING else 0,
            )
        )

        return items

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

        # Check cache first (and mark as recently used)
        if path_str in self._size_cache:
            self._size_cache.move_to_end(path_str)
            return self._size_cache[path_str]

        total = 0

        try:
            if path.is_file():
                stat = path.stat()
                # Use st_blocks for actual disk usage (handles sparse files)
                # st_blocks is in 512-byte units
                total = stat.st_blocks * 512
            elif path.is_dir():
                # Use du command - much faster than Python os.walk
                # -s: summarize (total only)
                # -k: output in KB
                # Note: du may return non-zero exit code due to permission errors
                # but still output the size, so we check stdout regardless
                proc = subprocess.Popen(
                    ["du", "-sk", path_str],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                # Track the process so it can be killed on shutdown
                with self._process_lock:
                    self._active_processes.append(proc)
                try:
                    stdout, _ = proc.communicate(timeout=60)
                    if stdout:
                        # Parse output: "12345\t/path/to/dir"
                        try:
                            size_kb = stdout.split()[0]
                            total = int(size_kb) * 1024
                        except (ValueError, IndexError):
                            pass
                finally:
                    # Remove from active processes
                    with self._process_lock:
                        if proc in self._active_processes:
                            self._active_processes.remove(proc)
        except (OSError, PermissionError, subprocess.TimeoutExpired, ValueError):
            pass

        # Cache the result with LRU eviction
        self._size_cache[path_str] = total
        # Move to end (most recently used)
        self._size_cache.move_to_end(path_str)
        # Evict oldest entries if cache is too large
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

        # Check exact matches
        if path_str in self.DANGEROUS_PATHS:
            return True

        # Check if path starts with dangerous paths
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
        self._size_cache.clear()

    def kill_active_processes(self) -> int:
        """
        Kill all active du processes.

        Call this when shutting down to ensure clean exit.

        Returns:
            Number of processes killed
        """
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
            # Create parent directories if needed
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            cache_data = {
                "version": 1,
                "timestamp": datetime.now().isoformat(),
                "sizes": self._size_cache,
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

        try:
            if not cache_path.exists():
                return 0

            with open(cache_path, "r") as f:
                cache_data = json.load(f)

            # Validate structure
            if not isinstance(cache_data, dict):
                return 0
            if "sizes" not in cache_data or not isinstance(cache_data["sizes"], dict):
                return 0

            # Check cache age
            timestamp_str = cache_data.get("timestamp")
            if timestamp_str:
                try:
                    cache_time = datetime.fromisoformat(timestamp_str)
                    age_hours = (datetime.now() - cache_time).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        return 0
                except (ValueError, TypeError):
                    pass

            # Load entries, validating each one
            loaded_count = 0
            for path_str, size in cache_data["sizes"].items():
                if not isinstance(size, int):
                    continue

                try:
                    path = Path(path_str)
                    if not path.exists():
                        continue

                    # Check if directory mtime changed (invalidates cache)
                    if path.is_dir():
                        # Skip validation for now - just load if exists
                        pass

                    self._size_cache[path_str] = size
                    loaded_count += 1
                except (OSError, PermissionError):
                    continue

            return loaded_count
        except (OSError, PermissionError, json.JSONDecodeError, TypeError):
            return 0

    def invalidate_cache(self, path: Path) -> None:
        """
        Remove a specific path and all its children from the cache.

        Args:
            path: Path to invalidate
        """
        path_str = str(path)
        path_prefix = path_str + "/"

        # Find all keys to remove
        keys_to_remove = [
            key
            for key in self._size_cache
            if key == path_str or key.startswith(path_prefix)
        ]

        # Remove them
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

        # Use a non-blocking approach so we can check stop_event
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            # Submit all tasks
            future_to_path = {
                executor.submit(self.calculate_size, path): path for path in paths
            }

            # Process results as they complete
            for future in as_completed(future_to_path):
                # Check if we should stop
                if stop_event is not None and stop_event.is_set():
                    # Cancel remaining futures
                    for f in future_to_path:
                        f.cancel()
                    break

                path = future_to_path[future]
                try:
                    size = future.result(timeout=0.1)
                    results[path] = size
                    if callback is not None:
                        callback(path, size)
                except Exception as e:
                    # Log the error and continue with other paths
                    logging.debug(f"Error calculating size for {path}: {e}")
                    # Store 0 for failed paths so caller knows it was processed
                    results[path] = 0
                    if callback is not None:
                        callback(path, 0)
        finally:
            # Shutdown without waiting - let threads die naturally
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

        # Convert to sets for efficient lookup
        all_paths_set = set(paths)
        priority_set = set(priority_paths)

        # Ensure priority paths are in the paths list
        priority_to_process = [p for p in priority_paths if p in all_paths_set]

        # Remaining paths (not in priority)
        remaining_paths = [p for p in paths if p not in priority_set]

        # Process priority paths first
        if priority_to_process:
            if stop_event is not None and stop_event.is_set():
                return results
            priority_results = self.calculate_sizes_parallel(
                priority_to_process, callback=callback, stop_event=stop_event
            )
            results.update(priority_results)

        # Then process remaining paths
        if remaining_paths:
            if stop_event is not None and stop_event.is_set():
                return results
            remaining_results = self.calculate_sizes_parallel(
                remaining_paths, callback=callback, stop_event=stop_event
            )
            results.update(remaining_results)

        return results
