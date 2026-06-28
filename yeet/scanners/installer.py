"""Scanner for downloaded installer files and bundles."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import InstallerItem, InstallerScanResults


class InstallerScanner:
    """Find downloaded installers in common locations."""

    DEFAULT_ROOTS: list[tuple[str, Path]] = [
        ("Downloads", Path.home() / "Downloads"),
        ("Desktop", Path.home() / "Desktop"),
        (
            "Homebrew Cache",
            Path.home() / "Library" / "Caches" / "Homebrew",
        ),
        (
            "Mail Downloads",
            Path.home()
            / "Library"
            / "Containers"
            / "com.apple.mail"
            / "Data"
            / "Library"
            / "Mail Downloads",
        ),
    ]

    FILE_EXTENSIONS = (
        ".dmg",
        ".pkg",
        ".mpkg",
        ".zip",
        ".tar.gz",
        ".tgz",
        ".tar.xz",
        ".iso",
    )

    MIN_SIZE_BYTES = 25 * 1024 * 1024

    def scan(
        self,
        root: Path | None = None,
        progress_callback: Callable[[int, str], None] | None = None,
        min_size_mb: int = 25,
    ) -> InstallerScanResults:
        results = InstallerScanResults()
        min_size_bytes = min_size_mb * 1024 * 1024

        if root is not None:
            self._scan_root(results, root, "Custom", min_size_bytes, progress_callback)
        else:
            for source, path in self.DEFAULT_ROOTS:
                if path.exists():
                    self._scan_root(
                        results, path, source, min_size_bytes, progress_callback
                    )

        results.items.sort(key=lambda item: item.size, reverse=True)
        return results

    def _scan_root(
        self,
        results: InstallerScanResults,
        root: Path,
        source: str,
        min_size_bytes: int,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        try:
            for current_root, dirs, files in os.walk(root):
                # Don't dive too deep into caches for homebrew / mail downloads.
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                current_path = Path(current_root)

                for name in files:
                    candidate = current_path / name
                    try:
                        if not self._is_installer_file(candidate):
                            continue

                        stat = candidate.stat()
                        if stat.st_size < min_size_bytes:
                            continue

                        item = InstallerItem(
                            path=candidate,
                            name=name,
                            source=source,
                            size=stat.st_size,
                            last_modified=datetime.fromtimestamp(stat.st_mtime),
                            extension=self._get_extension(name),
                        )
                        results.items.append(item)
                        if progress_callback:
                            progress_callback(len(results.items), name)
                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{candidate}: {e}")

                for dirname in list(dirs):
                    if not self._is_installer_bundle(dirname):
                        continue

                    candidate = current_path / dirname
                    try:
                        stat = candidate.stat()
                        total = self._get_directory_size(candidate)
                        if total < min_size_bytes:
                            continue

                        item = InstallerItem(
                            path=candidate,
                            name=dirname,
                            source=source,
                            size=total,
                            last_modified=datetime.fromtimestamp(stat.st_mtime),
                            extension=self._get_extension(dirname),
                        )
                        results.items.append(item)
                        if progress_callback:
                            progress_callback(len(results.items), dirname)
                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{candidate}: {e}")
        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{root}: {e}")

    def _is_installer_file(self, path: Path) -> bool:
        name = path.name.lower()
        return any(name.endswith(ext) for ext in self.FILE_EXTENSIONS)

    def _is_installer_bundle(self, dirname: str) -> bool:
        lower = dirname.lower()
        return lower.endswith(".app")

    def _get_extension(self, name: str) -> str:
        lower = name.lower()
        for ext in self.FILE_EXTENSIONS:
            if lower.endswith(ext):
                return ext
        if lower.endswith(".app"):
            return ".app"
        return Path(name).suffix.lower() or "—"

    def _get_directory_size(self, path: Path) -> int:
        total = 0
        try:
            for root, _, files in os.walk(path):
                for name in files:
                    try:
                        total += (Path(root) / name).stat().st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total
