"""Cache scanner for finding browser, package manager, and app caches."""

from __future__ import annotations

import os
import platform
import subprocess
from glob import glob
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import (
    CacheCategory,
    CacheLocation,
    CacheScanResults,
)


class CacheScanner:
    """
    Scans for common cache directories across different operating systems.

    Detects caches for:
    - Browsers (Chrome, Firefox, Safari, Edge)
    - Package managers (npm, yarn, pip, cargo, go, gradle, cocoapods, etc.)
    - Build tools (Xcode, Android, CMake, Bazel)
    - Containers (Docker, Podman)
    - IDEs/Editors (VS Code, JetBrains, Xcode)
    - System caches
    - Runtime caches (Python, Ruby, Java)
    """

    # Cache definitions: (name, category, relative_paths_by_os)
    # Paths are relative to home directory unless starting with /
    CACHE_DEFINITIONS: list[tuple[str, CacheCategory, dict[str, list[str]]]] = [
        # =====================
        # BROWSER CACHES
        # =====================
        (
            "Google Chrome Cache",
            CacheCategory.BROWSER,
            {
                "darwin": [
                    "Library/Caches/Google/Chrome",
                    "Library/Application Support/Google/Chrome/Default/Cache",
                    "Library/Application Support/Google/Chrome/Default/Code Cache",
                ],
                "linux": [
                    ".cache/google-chrome",
                    ".config/google-chrome/Default/Cache",
                ],
                "windows": [
                    "AppData/Local/Google/Chrome/User Data/Default/Cache",
                    "AppData/Local/Google/Chrome/User Data/Default/Code Cache",
                ],
            },
        ),
        (
            "Firefox Cache",
            CacheCategory.BROWSER,
            {
                "darwin": ["Library/Caches/Firefox/Profiles"],
                "linux": [".cache/mozilla/firefox"],
                "windows": ["AppData/Local/Mozilla/Firefox/Profiles"],
            },
        ),
        (
            "Safari Cache",
            CacheCategory.BROWSER,
            {
                "darwin": ["Library/Caches/com.apple.Safari"],
            },
        ),
        (
            "Microsoft Edge Cache",
            CacheCategory.BROWSER,
            {
                "darwin": ["Library/Caches/Microsoft Edge"],
                "linux": [".cache/microsoft-edge"],
                "windows": ["AppData/Local/Microsoft/Edge/User Data/Default/Cache"],
            },
        ),
        (
            "Brave Cache",
            CacheCategory.BROWSER,
            {
                "darwin": [
                    "Library/Caches/BraveSoftware/Brave-Browser",
                    "Library/Application Support/BraveSoftware/Brave-Browser/Default/Cache",
                ],
                "linux": [".cache/BraveSoftware/Brave-Browser"],
                "windows": [
                    "AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/Cache"
                ],
            },
        ),
        (
            "Arc Cache",
            CacheCategory.BROWSER,
            {
                "darwin": [
                    "Library/Caches/company.thebrowser.Browser",
                ],
            },
        ),
        # =====================
        # PACKAGE MANAGERS
        # =====================
        (
            "npm Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".npm/_cacache", "Library/Caches/npm"],
                "linux": [".npm/_cacache"],
                "windows": ["AppData/Local/npm-cache", "AppData/Roaming/npm-cache"],
            },
        ),
        (
            "Yarn Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/Yarn", ".yarn/cache"],
                "linux": [".cache/yarn", ".yarn/cache"],
                "windows": ["AppData/Local/Yarn/Cache"],
            },
        ),
        (
            "pnpm Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/pnpm"],
                "linux": [".cache/pnpm"],
                "windows": ["AppData/Local/pnpm/Cache"],
            },
        ),
        (
            "Bun Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".bun/install/cache"],
                "linux": [".bun/install/cache"],
                "windows": [".bun/install/cache"],
            },
        ),
        (
            "pip Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/pip"],
                "linux": [".cache/pip"],
                "windows": ["AppData/Local/pip/Cache"],
            },
        ),
        (
            "Poetry Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/pypoetry"],
                "linux": [".cache/pypoetry"],
                "windows": ["AppData/Local/pypoetry/Cache"],
            },
        ),
        (
            "uv Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/uv"],
                "linux": [".cache/uv"],
                "windows": ["AppData/Local/uv/cache"],
            },
        ),
        (
            "Go Module Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["go/pkg/mod/cache"],
                "linux": ["go/pkg/mod/cache"],
                "windows": ["go/pkg/mod/cache"],
            },
        ),
        (
            "Gradle Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".gradle/caches"],
                "linux": [".gradle/caches"],
                "windows": [".gradle/caches"],
            },
        ),
        (
            "CocoaPods Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/CocoaPods"],
            },
        ),
        (
            "RubyGems Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/gem"],
                "linux": [".cache/gem"],
                "windows": [],
            },
        ),
        (
            "Composer Cache (PHP)",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".composer/cache", "Library/Caches/composer"],
                "linux": [".composer/cache", ".cache/composer"],
                "windows": ["AppData/Local/Composer"],
            },
        ),
        (
            "Homebrew Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": ["Library/Caches/Homebrew"],
                "linux": [".cache/Homebrew"],
            },
        ),
        # =====================
        # BUILD TOOLS
        # =====================
        (
            "Xcode Derived Data",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Developer/Xcode/DerivedData"],
            },
        ),
        (
            "CoreSimulator Caches",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Developer/CoreSimulator/Caches"],
            },
        ),
        (
            "Android SDK Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": [
                    "Library/Android/sdk/.downloadIntermediates",
                    ".android/cache",
                ],
                "linux": [
                    ".android/cache",
                    "Android/Sdk/.downloadIntermediates",
                ],
                "windows": [
                    ".android/cache",
                    "AppData/Local/Android/Sdk/.downloadIntermediates",
                ],
            },
        ),
        (
            "CMake Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": [".cmake/packages"],
                "linux": [".cmake/packages"],
                "windows": [".cmake/packages"],
            },
        ),
        (
            "Bazel Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": [".cache/bazel", "Library/Caches/bazel"],
                "linux": [".cache/bazel"],
                "windows": ["AppData/Local/bazel"],
            },
        ),
        (
            "ccache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Caches/ccache", ".ccache"],
                "linux": [".cache/ccache", ".ccache"],
                "windows": ["AppData/Local/ccache"],
            },
        ),
        (
            "Webpack Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": [".cache/webpack"],
                "linux": [".cache/webpack"],
                "windows": [".cache/webpack"],
            },
        ),
        (
            "Turborepo Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Caches/turbo"],
                "linux": [".cache/turbo"],
                "windows": ["AppData/Local/turbo"],
            },
        ),
        (
            "node-gyp Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Caches/node-gyp"],
                "linux": [".cache/node-gyp"],
                "windows": ["AppData/Local/node-gyp"],
            },
        ),
        # =====================
        # CONTAINERS
        # =====================
        (
            "Minikube Cache",
            CacheCategory.CONTAINER,
            {
                "darwin": [".minikube/cache"],
                "linux": [".minikube/cache"],
                "windows": [".minikube/cache"],
            },
        ),
        # =====================
        # IDE / EDITORS
        # =====================
        (
            "VS Code Cache",
            CacheCategory.IDE,
            {
                "darwin": [
                    "Library/Application Support/Code/Cache",
                    "Library/Application Support/Code/CachedData",
                    "Library/Application Support/Code/CachedExtensions",
                    "Library/Application Support/Code/CachedExtensionVSIXs",
                    "Library/Caches/com.microsoft.VSCode",
                ],
                "linux": [".config/Code/Cache", ".config/Code/CachedData"],
                "windows": [
                    "AppData/Roaming/Code/Cache",
                    "AppData/Roaming/Code/CachedData",
                ],
            },
        ),
        (
            "Cursor Cache",
            CacheCategory.IDE,
            {
                "darwin": [
                    "Library/Application Support/Cursor/Cache",
                    "Library/Application Support/Cursor/CachedData",
                    "Library/Caches/com.todesktop.230313mzl4w4u92",
                ],
                "linux": [".config/Cursor/Cache", ".config/Cursor/CachedData"],
                "windows": [
                    "AppData/Roaming/Cursor/Cache",
                    "AppData/Roaming/Cursor/CachedData",
                ],
            },
        ),
        (
            "JetBrains IDEs Cache",
            CacheCategory.IDE,
            {
                "darwin": ["Library/Caches/JetBrains"],
                "linux": [".cache/JetBrains"],
                "windows": [],
            },
        ),
        (
            "Sublime Text Cache",
            CacheCategory.IDE,
            {
                "darwin": ["Library/Caches/com.sublimetext.4"],
                "linux": [".cache/sublime-text"],
                "windows": ["AppData/Local/Sublime Text/Cache"],
            },
        ),
        (
            "Vim/Neovim Cache",
            CacheCategory.IDE,
            {
                "darwin": [".cache/nvim"],
                "linux": [".cache/nvim"],
                "windows": [],
            },
        ),
        (
            "Zed Cache",
            CacheCategory.IDE,
            {
                "darwin": ["Library/Caches/dev.zed.Zed"],
            },
        ),
        # =====================
        # SYSTEM CACHES
        # =====================
        # Note: We don't include the top-level cache directories (~/Library/Caches,
        # ~/.cache) because:
        # 1. They contain many app-specific caches we already scan individually
        # 2. Some subdirectories have restricted permissions (SIP-protected on macOS)
        # 3. Deleting them as a whole often fails or times out
        # Instead, we scan specific cache subdirectories above.
        (
            "Thumbnails Cache",
            CacheCategory.SYSTEM,
            {
                "darwin": ["Library/Caches/com.apple.QuickLook.thumbnailcache"],
                "linux": [".cache/thumbnails"],
                "windows": ["AppData/Local/Microsoft/Windows/Explorer"],
            },
        ),
        (
            "Font Cache",
            CacheCategory.SYSTEM,
            {
                "darwin": ["Library/Caches/com.apple.FontRegistry"],
                "linux": [".cache/fontconfig"],
                "windows": ["AppData/Local/Microsoft/FontCache"],
            },
        ),
        # =====================
        # RUNTIME CACHES
        # =====================
        (
            "Python __pycache__",
            CacheCategory.RUNTIME,
            {
                "darwin": [],  # Handled separately - found in project dirs
                "linux": [],
                "windows": [],
            },
        ),
        # =====================
        # OTHER
        # =====================
        (
            "Electron Apps Cache",
            CacheCategory.OTHER,
            {
                "darwin": [
                    "Library/Application Support/Slack/Cache",
                    "Library/Application Support/discord/Cache",
                    "Library/Application Support/Spotify/PersistentCache",
                    "Library/Caches/com.spotify.client",
                ],
                "linux": [
                    ".config/Slack/Cache",
                    ".config/discord/Cache",
                    ".cache/spotify",
                ],
                "windows": [
                    "AppData/Roaming/Slack/Cache",
                    "AppData/Roaming/discord/Cache",
                    "AppData/Local/Spotify/Storage",
                ],
            },
        ),
        (
            "App Updater Caches",
            CacheCategory.OTHER,
            {
                # Many Electron apps use Squirrel/ShipIt for updates
                # These caches can grow large and are safe to clear
                "darwin": [
                    "Library/Caches/com.microsoft.autoupdate2",
                    "Library/Caches/com.microsoft.autoupdate.fba",
                ],
                "linux": [],
                "windows": [],
            },
        ),
    ]

    def __init__(self) -> None:
        """Initialize the cache scanner with OS detection."""
        self.os_type = self._detect_os()
        self.home = Path.home()

    @staticmethod
    def _detect_os() -> str:
        """Detect the current operating system."""
        system = platform.system().lower()
        if system == "darwin":
            return "darwin"
        elif system == "linux":
            return "linux"
        elif system == "windows":
            return "windows"
        else:
            return "linux"  # Default to Linux for unknown systems

    def _get_directory_stats(self, path: Path) -> tuple[int, int, datetime]:
        """
        Get total size, file count, and last modified time for a directory.

        Returns:
            Tuple of (total_size, file_count, last_modified)
        """
        total_size = 0
        file_count = 0
        latest_mtime = path.stat().st_mtime if path.exists() else 0

        try:
            for root, dirs, files in os.walk(path):
                for fname in files:
                    try:
                        fpath = Path(root) / fname
                        stat = fpath.stat()
                        total_size += stat.st_size
                        file_count += 1
                        if stat.st_mtime > latest_mtime:
                            latest_mtime = stat.st_mtime
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass

        return total_size, file_count, datetime.fromtimestamp(latest_mtime)

    def _expand_candidate_paths(self, rel_path: str) -> list[Path]:
        raw_paths: list[str]
        if any(char in rel_path for char in "*?[]"):
            pattern = rel_path
            if not rel_path.startswith("/"):
                pattern = str(self.home / rel_path)
            raw_paths = glob(pattern)
        else:
            raw_paths = [
                str(
                    Path(rel_path) if rel_path.startswith("/") else self.home / rel_path
                )
            ]

        paths: list[Path] = []
        for raw_path in raw_paths:
            path = Path(raw_path)
            try:
                if path.exists() and path.is_dir() and not path.is_symlink():
                    paths.append(path)
            except OSError:
                continue
        return paths

    def _expand_browser_cache_paths(
        self,
    ) -> list[tuple[str, CacheCategory, Path, bool]]:
        if self.os_type != "darwin":
            return []

        browser_roots = [
            ("Chrome", "Library/Application Support/Google/Chrome"),
            ("Brave", "Library/Application Support/BraveSoftware/Brave-Browser"),
            ("Edge", "Library/Application Support/Microsoft Edge"),
            ("Arc", "Library/Application Support/company.thebrowser.Browser"),
            ("Vivaldi", "Library/Application Support/Vivaldi"),
            ("Opera", "Library/Application Support/com.operasoftware.Opera"),
        ]
        browser_subdirs = [
            "*/Code Cache",
            "*/GPUCache",
            "*/DawnCache",
            "*/GrShaderCache",
            "*/GraphiteDawnCache",
            "*/Cache",
        ]

        candidates: list[tuple[str, CacheCategory, Path, bool]] = []
        for browser_name, browser_root in browser_roots:
            for subdir in browser_subdirs:
                pattern = f"{browser_root}/{subdir}"
                for path in self._expand_candidate_paths(pattern):
                    candidates.append(
                        (f"{browser_name} Cache", CacheCategory.BROWSER, path, False)
                    )
        return candidates

    def _expand_container_cache_paths(
        self,
    ) -> list[tuple[str, CacheCategory, Path, bool]]:
        if self.os_type != "darwin":
            return []

        candidates: list[tuple[str, CacheCategory, Path, bool]] = []
        patterns = [
            (
                "Sandboxed App Cache",
                CacheCategory.CONTAINER,
                "Library/Containers/*/Data/Library/Caches",
                True,
            ),
            (
                "Group Container Cache",
                CacheCategory.CONTAINER,
                "Library/Group Containers/*/Caches",
                True,
            ),
            (
                "Group Container Cache",
                CacheCategory.CONTAINER,
                "Library/Group Containers/*/Library/Caches",
                True,
            ),
        ]
        for name, category, pattern, delete_contents_only in patterns:
            for path in self._expand_candidate_paths(pattern):
                bundle_root = path
                candidates.append((name, category, bundle_root, delete_contents_only))
        return candidates

    def _darwin_user_cache_paths(self) -> list[tuple[str, CacheCategory, Path, bool]]:
        if self.os_type != "darwin":
            return []

        candidates: list[tuple[str, CacheCategory, Path, bool]] = []
        for key, label in (("DARWIN_USER_CACHE_DIR", "Darwin User Cache"),):
            try:
                result = subprocess.run(
                    ["getconf", key], capture_output=True, text=True, check=True
                )
            except (OSError, subprocess.CalledProcessError):
                continue

            value = result.stdout.strip()
            if not value:
                continue
            path = Path(value)
            try:
                if path.exists() and path.is_dir() and not path.is_symlink():
                    candidates.append((label, CacheCategory.SYSTEM, path, True))
            except OSError:
                continue

        return candidates

    def _extra_candidates(self) -> list[tuple[str, CacheCategory, Path, bool]]:
        if self.os_type != "darwin":
            return []

        extra: list[tuple[str, CacheCategory, Path, bool]] = []
        for name, rel_path, delete_contents_only in [
            (
                "WebKit Networking Cache",
                "Library/Caches/com.apple.WebKit.Networking",
                False,
            ),
            ("Quick Look Cache", "Library/Caches/Quick Look", False),
            (
                "QuickLook Thumbnail Cache",
                "Library/Caches/com.apple.QuickLook.thumbnailcache",
                False,
            ),
            ("Icon Services Cache", "Library/Caches/com.apple.iconservices*", False),
            ("Apple ID Cache", "Library/Caches/com.apple.akd", False),
            ("Photo Analysis Cache", "Library/Caches/com.apple.photoanalysisd", False),
        ]:
            for path in self._expand_candidate_paths(rel_path):
                extra.append((name, CacheCategory.SYSTEM, path, delete_contents_only))

        extra.extend(self._expand_browser_cache_paths())
        extra.extend(self._expand_container_cache_paths())
        extra.extend(self._darwin_user_cache_paths())
        return extra

    def scan(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
        min_size_mb: int = 1,
    ) -> CacheScanResults:
        """
        Scan for cache directories.

        Args:
            progress_callback: Optional callback(caches_found, current_name)
            min_size_mb: Minimum cache size in MB to include (default 1MB)

        Returns:
            CacheScanResults containing all found caches
        """
        results = CacheScanResults()
        min_size_bytes = min_size_mb * 1024 * 1024
        found_paths: set[Path] = set()  # Track to avoid duplicates

        def add_candidate(
            name: str,
            category: CacheCategory,
            path: Path,
            delete_contents_only: bool = False,
        ) -> None:
            try:
                resolved = path.resolve()
            except OSError:
                return

            if resolved in found_paths:
                return
            if not resolved.exists() or not resolved.is_dir() or resolved.is_symlink():
                return

            found_paths.add(resolved)
            size, file_count, last_modified = self._get_directory_stats(resolved)
            if size < min_size_bytes:
                return

            is_xcode = name.startswith("Xcode") or name.startswith("CoreSimulator")
            cache = CacheLocation(
                path=resolved,
                name=name,
                category=category,
                size=size,
                file_count=file_count,
                last_modified=last_modified,
                is_xcode=is_xcode,
                delete_contents_only=delete_contents_only,
            )
            results.caches.append(cache)
            if progress_callback:
                progress_callback(len(results.caches), name)

        for name, category, paths_by_os in self.CACHE_DEFINITIONS:
            os_paths = paths_by_os.get(self.os_type, [])

            for rel_path in os_paths:
                try:
                    for path in self._expand_candidate_paths(rel_path):
                        add_candidate(name, category, path)
                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{rel_path}: {e}")
                    continue

        for name, category, path, delete_contents_only in self._extra_candidates():
            add_candidate(name, category, path, delete_contents_only)

        # Sort by size (largest first)
        results.caches.sort(key=lambda c: c.size, reverse=True)

        return results
