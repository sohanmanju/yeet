"""Cache scanner for finding browser, package manager, and app caches."""

from __future__ import annotations

import os
import platform
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
    - Package managers (npm, yarn, pip, cargo, go, maven, gradle, cocoapods, etc.)
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
                "darwin": [
                    "Library/Caches/com.apple.Safari",
                    "Library/Safari/LocalStorage",
                ],
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
                "darwin": ["Library/pnpm/store", "Library/Caches/pnpm"],
                "linux": [".local/share/pnpm/store", ".cache/pnpm"],
                "windows": ["AppData/Local/pnpm/store"],
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
            "Cargo Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".cargo/registry", ".cargo/git"],
                "linux": [".cargo/registry", ".cargo/git"],
                "windows": [".cargo/registry", ".cargo/git"],
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
            "Maven Cache",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".m2/repository"],
                "linux": [".m2/repository"],
                "windows": [".m2/repository"],
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
                "darwin": [".gem/ruby", "Library/Caches/gem"],
                "linux": [".gem/ruby", ".cache/gem"],
                "windows": [".gem/ruby"],
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
            "Pub Cache (Dart/Flutter)",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".pub-cache"],
                "linux": [".pub-cache"],
                "windows": ["AppData/Local/Pub/Cache"],
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
        (
            "NuGet Cache (.NET)",
            CacheCategory.PACKAGE_MANAGER,
            {
                "darwin": [".nuget/packages"],
                "linux": [".nuget/packages"],
                "windows": [".nuget/packages", "AppData/Local/NuGet/Cache"],
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
            "Xcode Archives",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Developer/Xcode/Archives"],
            },
        ),
        (
            "Xcode iOS DeviceSupport",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Developer/Xcode/iOS DeviceSupport"],
            },
        ),
        (
            "Xcode watchOS DeviceSupport",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Developer/Xcode/watchOS DeviceSupport"],
            },
        ),
        (
            "CoreSimulator Caches",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": [
                    "Library/Developer/CoreSimulator/Caches",
                    "Library/Developer/CoreSimulator/Devices",
                ],
            },
        ),
        (
            "Android SDK Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": [
                    "Library/Android/sdk/.downloadIntermediates",
                    ".android/cache",
                    ".android/avd",
                ],
                "linux": [
                    ".android/cache",
                    ".android/avd",
                    "Android/Sdk/.downloadIntermediates",
                ],
                "windows": [
                    ".android/cache",
                    ".android/avd",
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
            "Playwright Cache",
            CacheCategory.BUILD_TOOL,
            {
                "darwin": ["Library/Caches/ms-playwright"],
                "linux": [".cache/ms-playwright"],
                "windows": ["AppData/Local/ms-playwright"],
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
            "Docker Desktop Data",
            CacheCategory.CONTAINER,
            {
                "darwin": [
                    "Library/Containers/com.docker.docker/Data/vms",
                    ".docker/buildx",
                ],
                "linux": [".docker/buildx", "/var/lib/docker"],
                "windows": ["AppData/Local/Docker/wsl"],
            },
        ),
        (
            "Colima (Docker) Cache",
            CacheCategory.CONTAINER,
            {
                "darwin": [".colima"],
            },
        ),
        (
            "Podman Cache",
            CacheCategory.CONTAINER,
            {
                "darwin": [".local/share/containers"],
                "linux": [".local/share/containers", "/var/lib/containers"],
                "windows": ["AppData/Local/containers"],
            },
        ),
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
            "VS Code Extensions",
            CacheCategory.IDE,
            {
                "darwin": [".vscode/extensions"],
                "linux": [".vscode/extensions"],
                "windows": [".vscode/extensions"],
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
                "darwin": [
                    "Library/Caches/JetBrains",
                    "Library/Application Support/JetBrains",
                ],
                "linux": [".cache/JetBrains", ".local/share/JetBrains"],
                "windows": ["AppData/Local/JetBrains"],
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
                "darwin": [".vim/undodir", ".local/share/nvim", ".cache/nvim"],
                "linux": [".vim/undodir", ".local/share/nvim", ".cache/nvim"],
                "windows": ["AppData/Local/nvim-data"],
            },
        ),
        (
            "Zed Cache",
            CacheCategory.IDE,
            {
                "darwin": [
                    "Library/Caches/dev.zed.Zed",
                    "Library/Application Support/Zed/languages",
                ],
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
            "Temporary Files",
            CacheCategory.SYSTEM,
            {
                # Only include truly temporary directories that are safe to clear
                "darwin": ["Library/Caches/TemporaryItems"],
                "linux": [".cache/tmp"],
                "windows": ["AppData/Local/Temp"],
            },
        ),
        (
            "Logs",
            CacheCategory.SYSTEM,
            {
                "darwin": ["Library/Logs"],
                "linux": [".local/share/logs", "/var/log"],
                "windows": ["AppData/Local/Logs"],
            },
        ),
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
            "Spotlight Index",
            CacheCategory.SYSTEM,
            {
                "darwin": [".Spotlight-V100"],
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
        (
            "Python Virtual Envs (global)",
            CacheCategory.RUNTIME,
            {
                "darwin": [".virtualenvs"],
                "linux": [".virtualenvs"],
                "windows": ["Envs"],
            },
        ),
        (
            "pyenv Versions",
            CacheCategory.RUNTIME,
            {
                "darwin": [".pyenv/versions", ".pyenv/cache"],
                "linux": [".pyenv/versions", ".pyenv/cache"],
                "windows": [".pyenv/pyenv-win/versions"],
            },
        ),
        (
            "rbenv/Ruby Versions",
            CacheCategory.RUNTIME,
            {
                "darwin": [".rbenv/versions"],
                "linux": [".rbenv/versions"],
            },
        ),
        (
            "nvm Node Versions",
            CacheCategory.RUNTIME,
            {
                "darwin": [".nvm/versions"],
                "linux": [".nvm/versions"],
                "windows": ["AppData/Roaming/nvm"],
            },
        ),
        (
            "fnm Node Versions",
            CacheCategory.RUNTIME,
            {
                "darwin": ["Library/Application Support/fnm/node-versions"],
                "linux": [".local/share/fnm/node-versions"],
                "windows": ["AppData/Roaming/fnm/node-versions"],
            },
        ),
        (
            "rustup Toolchains",
            CacheCategory.RUNTIME,
            {
                "darwin": [".rustup/toolchains"],
                "linux": [".rustup/toolchains"],
                "windows": [".rustup/toolchains"],
            },
        ),
        (
            "SDKMAN! Candidates",
            CacheCategory.RUNTIME,
            {
                "darwin": [".sdkman/candidates", ".sdkman/archives"],
                "linux": [".sdkman/candidates", ".sdkman/archives"],
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
        (
            "Trash",
            CacheCategory.OTHER,
            {
                "darwin": [".Trash"],
                "linux": [".local/share/Trash"],
                "windows": ["$Recycle.Bin"],
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

        for name, category, paths_by_os in self.CACHE_DEFINITIONS:
            os_paths = paths_by_os.get(self.os_type, [])

            for rel_path in os_paths:
                try:
                    # Handle absolute paths (like /var/lib/docker)
                    if rel_path.startswith("/"):
                        path = Path(rel_path)
                    else:
                        path = self.home / rel_path

                    # Skip if already processed or doesn't exist
                    if path in found_paths or not path.exists():
                        continue

                    # Skip if not a directory
                    if not path.is_dir():
                        continue

                    found_paths.add(path)

                    # Get directory stats
                    size, file_count, last_modified = self._get_directory_stats(path)

                    # Skip if below minimum size
                    if size < min_size_bytes:
                        continue

                    # Determine if this is an Xcode-related cache
                    is_xcode = name.startswith("Xcode") or name.startswith(
                        "CoreSimulator"
                    )

                    cache = CacheLocation(
                        path=path,
                        name=name,
                        category=category,
                        size=size,
                        file_count=file_count,
                        last_modified=last_modified,
                        is_xcode=is_xcode,
                    )
                    results.caches.append(cache)

                    if progress_callback:
                        progress_callback(len(results.caches), name)

                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{rel_path}: {e}")
                    continue

        # Sort by size (largest first)
        results.caches.sort(key=lambda c: c.size, reverse=True)

        return results
