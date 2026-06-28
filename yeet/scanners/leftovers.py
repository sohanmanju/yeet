"""Scanner for leftover app data from uninstalled apps."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import LeftoverItem, LeftoverScanResults


class LeftoverScanner:
    """Find app leftovers in common macOS library locations."""

    ROOTS: list[tuple[str, Path]] = [
        ("Application Support", Path.home() / "Library" / "Application Support"),
        ("Caches", Path.home() / "Library" / "Caches"),
        ("Preferences", Path.home() / "Library" / "Preferences"),
        ("Logs", Path.home() / "Library" / "Logs"),
        ("WebKit", Path.home() / "Library" / "WebKit"),
        ("Containers", Path.home() / "Library" / "Containers"),
        ("LaunchAgents", Path.home() / "Library" / "LaunchAgents"),
    ]

    def __init__(self) -> None:
        self.installed_apps = self._discover_installed_apps()

    def scan(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> LeftoverScanResults:
        results = LeftoverScanResults()
        scanned = 0

        for source, root in self.ROOTS:
            if not root.exists():
                continue

            try:
                for entry in os.scandir(root):
                    try:
                        if not self._is_candidate(source, entry.name):
                            continue
                        if not self._looks_like_leftover(entry.name):
                            continue
                        if self._matches_installed_app(entry.name):
                            continue

                        path = Path(entry.path)
                        size = self._get_size(path)
                        if size <= 0:
                            continue

                        scanned += 1
                        item = LeftoverItem(
                            path=path,
                            name=entry.name,
                            source=source,
                            size=size,
                            last_modified=datetime.fromtimestamp(path.stat().st_mtime),
                            app_hint=self._app_hint(entry.name),
                        )
                        results.items.append(item)
                        if progress_callback:
                            progress_callback(scanned, entry.name)
                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{entry.path}: {e}")
            except (OSError, PermissionError) as e:
                results.scan_errors.append(f"{root}: {e}")

        results.items.sort(key=lambda item: item.size, reverse=True)
        return results

    def _discover_installed_apps(self) -> set[str]:
        names: set[str] = set()
        app_roots = [Path("/Applications"), Path.home() / "Applications"]
        for root in app_roots:
            if not root.exists():
                continue
            try:
                for entry in os.scandir(root):
                    if entry.is_dir() and entry.name.lower().endswith(".app"):
                        names.add(entry.name[:-4].casefold())
            except (OSError, PermissionError):
                continue
        return names

    def _is_candidate(self, source: str, name: str) -> bool:
        if source in {"Preferences", "LaunchAgents"}:
            return name.endswith(".plist")
        return True

    def _looks_like_leftover(self, name: str) -> bool:
        lowered = name.casefold()
        return not lowered.startswith("com.apple") and lowered not in {".ds_store"}

    def _matches_installed_app(self, name: str) -> bool:
        lowered = name.casefold()
        stem = lowered.removesuffix(".plist")
        for installed in self.installed_apps:
            if installed in lowered or installed in stem:
                return True
        return False

    def _app_hint(self, name: str) -> str:
        stem = name.removesuffix(".plist")
        if stem.startswith("com."):
            parts = stem.split(".")
            if len(parts) > 1:
                return parts[-1]
        return stem

    def _get_size(self, path: Path) -> int:
        if path.is_file():
            try:
                return path.stat().st_size
            except (OSError, PermissionError):
                return 0

        total = 0
        try:
            for root, _, files in os.walk(path):
                for fname in files:
                    try:
                        total += (Path(root) / fname).stat().st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total
