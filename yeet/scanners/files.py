"""Large file scanner for finding space-hogging files."""

from __future__ import annotations

import os
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import (
    DEFAULT_LARGE_FILE_MB,
    LargeFile,
    LargeFileScanResults,
)


class LargeFileScanner:
    """
    Scans for large files in a directory tree.

    Finds files exceeding a size threshold, useful for identifying
    space hogs like videos, disk images, build artifacts, etc.
    """

    # Directories to skip entirely
    SKIP_DIRS = frozenset(
        {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            ".Trash",
            "Library",  # macOS system
            ".cache",
        }
    )

    def __init__(
        self,
        min_size_mb: int = DEFAULT_LARGE_FILE_MB,
    ) -> None:
        """
        Args:
            min_size_mb: Minimum file size in MB to flag as large
        """
        self.min_size_bytes = min_size_mb * 1024 * 1024

    def scan(
        self,
        root: Path,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> LargeFileScanResults:
        """
        Scan for large files under root directory.

        Args:
            root: Root directory to search
            progress_callback: Optional callback(files_scanned, large_found, current_file)

        Returns:
            LargeFileScanResults containing all found large files
        """
        results = LargeFileScanResults()

        # BFS traversal
        dirs_to_scan: deque[Path] = deque([root])

        while dirs_to_scan:
            current_dir = dirs_to_scan.popleft()
            results.total_dirs_scanned += 1

            try:
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        try:
                            name = entry.name

                            if entry.is_dir(follow_symlinks=False):
                                # Skip certain directories
                                if name not in self.SKIP_DIRS and not name.startswith(
                                    "."
                                ):
                                    dirs_to_scan.append(Path(entry.path))

                            elif entry.is_file(follow_symlinks=False):
                                results.total_files_scanned += 1
                                stat = entry.stat(follow_symlinks=False)

                                if stat.st_size >= self.min_size_bytes:
                                    large_file = LargeFile(
                                        path=Path(entry.path),
                                        name=name,
                                        size=stat.st_size,
                                        last_accessed=datetime.fromtimestamp(
                                            stat.st_atime
                                        ),
                                        last_modified=datetime.fromtimestamp(
                                            stat.st_mtime
                                        ),
                                    )
                                    results.files.append(large_file)

                                    if progress_callback:
                                        progress_callback(
                                            results.total_files_scanned,
                                            len(results.files),
                                            name,
                                        )

                        except (OSError, PermissionError) as e:
                            results.scan_errors.append(f"{entry.path}: {e}")
                            continue

            except (OSError, PermissionError) as e:
                results.scan_errors.append(f"{current_dir}: {e}")
                continue

        # Sort by size (largest first)
        results.files.sort(key=lambda f: f.size, reverse=True)

        return results
