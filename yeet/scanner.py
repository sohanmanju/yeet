"""Project-level scanner for finding coding projects."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections import deque, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

import platform

from .utils import (
    DAYS_SINCE_ACCESS,
    DEFAULT_LARGE_FILE_MB,
    SKIP_FOR_SIZE,
    CacheCategory,
    CacheLocation,
    CacheScanResults,
    DiskItem,
    LargeFile,
    LargeFileScanResults,
    Project,
    ProjectType,
    SIZE_LOADING,
    ScanResults,
    XcodeItem,
    XcodeItemType,
    XcodeScanResults,
    is_macos,
    parse_xcode_version,
)


class ProjectScanner:
    """
    Scans for coding projects and analyzes their staleness.

    A project is identified by the presence of common project markers
    like package.json, pyproject.toml, Cargo.toml, .git, etc.

    Projects are treated as atomic units - we show project-level info,
    not individual files within projects.
    """

    def __init__(
        self,
        days_threshold: int = DAYS_SINCE_ACCESS,
        include_all: bool = False,
    ) -> None:
        """
        Args:
            days_threshold: Only include projects not modified in this many days
            include_all: If True, include all projects regardless of age
        """
        self.days_threshold = days_threshold
        self.include_all = include_all
        self._git_available = self._check_git_available()

    @staticmethod
    def _check_git_available() -> bool:
        """Check if git command is available."""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def scan(
        self,
        root: Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> ScanResults:
        """
        Scan for coding projects under root directory.

        Args:
            root: Root directory to search
            progress_callback: Optional callback(projects_found, current_dir)

        Returns:
            ScanResults containing all found projects
        """
        results = ScanResults()

        # BFS to find project directories
        dirs_to_scan: deque[Path] = deque([root])

        while dirs_to_scan:
            current_dir = dirs_to_scan.popleft()

            try:
                # Check if this directory is a project
                project_type = self._detect_project_type(current_dir)

                if project_type is not None:
                    # This is a project - analyze it
                    project = self._analyze_project(current_dir, project_type)

                    if project:
                        results.total_projects_scanned += 1
                        results.total_size_scanned += project.total_size

                        # Apply threshold filter
                        if (
                            self.include_all
                            or project.days_stale >= self.days_threshold
                        ):
                            results.projects.append(project)

                        if progress_callback:
                            progress_callback(
                                results.total_projects_scanned, current_dir.name
                            )

                    # Don't recurse into project directories
                    # (nested projects will be found when we scan subdirs that aren't projects)
                    continue

                # Not a project - scan subdirectories
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                name = entry.name
                                # Skip hidden dirs and known heavy directories
                                if (
                                    not name.startswith(".")
                                    and name not in SKIP_FOR_SIZE
                                ):
                                    dirs_to_scan.append(Path(entry.path))
                        except (OSError, PermissionError):
                            continue

            except (OSError, PermissionError) as e:
                results.scan_errors.append(f"{current_dir}: {e}")
                continue

        return results

    def _detect_project_type(self, path: Path) -> ProjectType | None:
        """
        Detect if directory is a coding project and return its type.

        Returns None if not a project.
        """
        try:
            entries = set()
            with os.scandir(path) as it:
                for entry in it:
                    entries.add(entry.name)

            # Check for git first (most common)
            if ".git" in entries:
                # Further classify by other markers
                if "package.json" in entries:
                    return ProjectType.NODE
                if (
                    "pyproject.toml" in entries
                    or "setup.py" in entries
                    or "requirements.txt" in entries
                ):
                    return ProjectType.PYTHON
                if "Cargo.toml" in entries:
                    return ProjectType.RUST
                if "go.mod" in entries:
                    return ProjectType.GO
                return ProjectType.GIT

            # Check for non-git projects
            if "package.json" in entries:
                return ProjectType.NODE
            if "pyproject.toml" in entries or "setup.py" in entries:
                return ProjectType.PYTHON
            if "Cargo.toml" in entries:
                return ProjectType.RUST
            if "go.mod" in entries:
                return ProjectType.GO
            if "Gemfile" in entries:
                return ProjectType.OTHER
            if "pom.xml" in entries or "build.gradle" in entries:
                return ProjectType.OTHER
            if "composer.json" in entries:
                return ProjectType.OTHER
            if "pubspec.yaml" in entries:
                return ProjectType.OTHER

            # Check for Xcode projects
            for name in entries:
                if name.endswith(".xcodeproj") or name.endswith(".xcworkspace"):
                    return ProjectType.OTHER

            return None

        except (OSError, PermissionError):
            return None

    def _analyze_project(self, path: Path, project_type: ProjectType) -> Project | None:
        """Analyze a project directory and extract metadata."""
        try:
            is_git = (path / ".git").is_dir()

            # Get last commit date if git repo
            last_commit = None
            if is_git:
                last_commit = self._get_last_commit_date(path)

            # Calculate size (excluding heavy directories)
            total_size = self._get_project_size(path)

            # Get last modified and accessed times of files in project
            last_modified, last_accessed = self._get_last_activity_times(path)

            return Project(
                path=path,
                name=path.name,
                project_type=project_type,
                total_size=total_size,
                last_modified=last_modified,
                last_accessed=last_accessed,
                last_commit_date=last_commit,
                is_git_repo=is_git,
            )
        except Exception:
            return None

    def _get_project_size(self, path: Path) -> int:
        """Calculate project size, excluding heavy directories like node_modules."""
        total = 0
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        name = entry.name
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            # Skip heavy directories
                            if name not in SKIP_FOR_SIZE and not name.startswith("."):
                                total += self._get_project_size(Path(entry.path))
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total

    def _get_last_activity_times(self, path: Path) -> tuple[datetime, datetime]:
        """
        Get the most recent modification and access times of any file in the project.

        Returns:
            Tuple of (last_modified, last_accessed) as datetime objects
        """
        stat = path.stat()
        latest_mtime = stat.st_mtime
        latest_atime = stat.st_atime

        try:
            for root, dirs, files in os.walk(path):
                # Skip heavy directories
                dirs[:] = [
                    d for d in dirs if d not in SKIP_FOR_SIZE and not d.startswith(".")
                ]

                for fname in files:
                    try:
                        fpath = Path(root) / fname
                        fstat = fpath.stat()

                        if fstat.st_mtime > latest_mtime:
                            latest_mtime = fstat.st_mtime

                        if fstat.st_atime > latest_atime:
                            latest_atime = fstat.st_atime
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass

        return datetime.fromtimestamp(latest_mtime), datetime.fromtimestamp(
            latest_atime
        )

    def _get_last_commit_date(self, project_path: Path) -> datetime | None:
        """Get the date of the last commit in a git repository."""
        if self._git_available:
            try:
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%ct"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0 and result.stdout.strip():
                    timestamp = int(result.stdout.strip())
                    return datetime.fromtimestamp(timestamp)
            except (subprocess.SubprocessError, ValueError, OSError):
                pass

        # Fallback: check .git file timestamps
        return self._get_last_commit_via_files(project_path)

    def _get_last_commit_via_files(self, project_path: Path) -> datetime | None:
        """Estimate last commit date from .git file modification times."""
        git_dir = project_path / ".git"

        files_to_check = [
            git_dir / "index",
            git_dir / "HEAD",
            git_dir / "COMMIT_EDITMSG",
            git_dir / "logs" / "HEAD",
        ]

        latest_mtime: float | None = None

        for file_path in files_to_check:
            try:
                if file_path.exists():
                    mtime = file_path.stat().st_mtime
                    if latest_mtime is None or mtime > latest_mtime:
                        latest_mtime = mtime
            except (OSError, PermissionError):
                continue

        if latest_mtime:
            return datetime.fromtimestamp(latest_mtime)

        return None


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
        (
            "System Cache",
            CacheCategory.SYSTEM,
            {
                "darwin": ["Library/Caches"],
                "linux": [".cache"],
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


class XcodeScanner:
    """
    Scans for Xcode-related data that can be cleaned up.

    Provides granular control over:
    - Device Support files (per iOS/watchOS/tvOS/visionOS version)
    - Derived Data (per project)
    - Archives (per archive with app version info)
    - Simulators (per device)
    - Documentation cache
    - Device logs

    Only runs on macOS.
    """

    # Xcode directories relative to home
    XCODE_PATHS = {
        "device_support": {
            "iOS": "Library/Developer/Xcode/iOS DeviceSupport",
            "watchOS": "Library/Developer/Xcode/watchOS DeviceSupport",
            "tvOS": "Library/Developer/Xcode/tvOS DeviceSupport",
            "visionOS": "Library/Developer/Xcode/visionOS DeviceSupport",
        },
        "derived_data": "Library/Developer/Xcode/DerivedData",
        "archives": "Library/Developer/Xcode/Archives",
        "simulators": "Library/Developer/CoreSimulator/Devices",
        "documentation": "Library/Developer/Xcode/DocumentationCache",
        "device_logs": "Library/Developer/Xcode/iOS Device Logs",
    }

    def __init__(self) -> None:
        """Initialize the Xcode scanner."""
        self.home = Path.home()

    def scan(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> XcodeScanResults:
        """
        Scan for Xcode-related items.

        Args:
            progress_callback: Optional callback(items_found, current_name)

        Returns:
            XcodeScanResults containing all found items
        """
        results = XcodeScanResults()

        # Only run on macOS
        if not is_macos():
            return results

        # Scan each category
        self._scan_device_support(results, progress_callback)
        self._scan_derived_data(results, progress_callback)
        self._scan_archives(results, progress_callback)
        self._scan_simulator_runtimes(results, progress_callback)
        self._scan_documentation(results, progress_callback)
        self._scan_device_logs(results, progress_callback)

        return results

    def _get_directory_size(self, path: Path) -> int:
        """Get total size of a directory."""
        total = 0
        try:
            for root, _, files in os.walk(path):
                for fname in files:
                    try:
                        fpath = Path(root) / fname
                        total += fpath.stat().st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total

    def _get_directory_mtime(self, path: Path) -> datetime:
        """Get most recent modification time in a directory."""
        try:
            latest = path.stat().st_mtime
            for root, _, files in os.walk(path):
                for fname in files:
                    try:
                        fpath = Path(root) / fname
                        mtime = fpath.stat().st_mtime
                        if mtime > latest:
                            latest = mtime
                    except (OSError, PermissionError):
                        continue
            return datetime.fromtimestamp(latest)
        except (OSError, PermissionError):
            return datetime.now()

    def _scan_device_support(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Device Support directories for each platform."""
        # Track latest version per platform for marking
        platform_versions: dict[str, list[tuple[tuple[int, ...], Path]]] = {}

        for platform_name, rel_path in self.XCODE_PATHS["device_support"].items():
            support_dir = self.home / rel_path

            if not support_dir.exists() or not support_dir.is_dir():
                continue

            platform_versions[platform_name] = []

            try:
                for entry in os.scandir(support_dir):
                    if not entry.is_dir():
                        continue

                    try:
                        version, build = parse_xcode_version(entry.name)
                        path = Path(entry.path)
                        size = self._get_directory_size(path)
                        mtime = self._get_directory_mtime(path)

                        # Track for latest detection
                        if version:
                            platform_versions[platform_name].append((version, path))

                        item = XcodeItem(
                            path=path,
                            name=entry.name,
                            item_type=XcodeItemType.DEVICE_SUPPORT,
                            size=size,
                            last_modified=mtime,
                            platform=platform_name,
                            version=version,
                            build=build,
                            is_latest=False,  # Will be set after scanning all
                        )
                        results.items.append(item)

                        if progress_callback:
                            progress_callback(
                                len(results.items), f"{platform_name} {entry.name}"
                            )

                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{entry.path}: {e}")

            except (OSError, PermissionError) as e:
                results.scan_errors.append(f"{support_dir}: {e}")

        # Mark latest versions per platform
        for platform_name, versions in platform_versions.items():
            if not versions:
                continue
            # Find the maximum version
            latest_version = max(versions, key=lambda x: x[0])[0]
            # Mark all items with this version as latest
            for item in results.items:
                if (
                    item.item_type == XcodeItemType.DEVICE_SUPPORT
                    and item.platform == platform_name
                    and item.version == latest_version
                ):
                    item.is_latest = True

    def _scan_derived_data(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Derived Data directory for build artifacts."""
        derived_data_dir = self.home / self.XCODE_PATHS["derived_data"]

        if not derived_data_dir.exists() or not derived_data_dir.is_dir():
            return

        try:
            for entry in os.scandir(derived_data_dir):
                if not entry.is_dir():
                    continue

                # Skip ModuleCache and other non-project dirs
                if entry.name in ("ModuleCache", "ModuleCache.noindex"):
                    continue

                try:
                    path = Path(entry.path)
                    size = self._get_directory_size(path)
                    mtime = self._get_directory_mtime(path)

                    # Extract project name from folder (format: ProjectName-hash)
                    parts = entry.name.rsplit("-", 1)
                    project_name = parts[0] if len(parts) > 1 else entry.name

                    item = XcodeItem(
                        path=path,
                        name=project_name,
                        item_type=XcodeItemType.DERIVED_DATA,
                        size=size,
                        last_modified=mtime,
                        platform=None,
                        version=None,
                        build=None,
                        is_latest=False,  # Derived data can always be deleted
                    )
                    results.items.append(item)

                    if progress_callback:
                        progress_callback(
                            len(results.items), f"Derived: {project_name}"
                        )

                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{entry.path}: {e}")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{derived_data_dir}: {e}")

    def _scan_archives(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Archives directory for app archives."""
        import plistlib

        archives_dir = self.home / self.XCODE_PATHS["archives"]

        if not archives_dir.exists() or not archives_dir.is_dir():
            return

        # Archives are organized by date: Archives/YYYY-MM-DD/*.xcarchive
        try:
            for date_entry in os.scandir(archives_dir):
                if not date_entry.is_dir():
                    continue

                for archive_entry in os.scandir(date_entry.path):
                    if not archive_entry.name.endswith(".xcarchive"):
                        continue

                    try:
                        path = Path(archive_entry.path)
                        size = self._get_directory_size(path)
                        mtime = self._get_directory_mtime(path)

                        # Try to parse Info.plist for app details
                        app_info = None
                        display_name = archive_entry.name.replace(".xcarchive", "")
                        info_plist = path / "Info.plist"

                        if info_plist.exists():
                            try:
                                with open(info_plist, "rb") as f:
                                    plist = plistlib.load(f)

                                app_props = plist.get("ApplicationProperties", {})
                                app_info = {
                                    "name": plist.get("Name", display_name),
                                    "bundle_id": app_props.get(
                                        "CFBundleIdentifier", "Unknown"
                                    ),
                                    "version": app_props.get(
                                        "CFBundleShortVersionString", "?"
                                    ),
                                    "build": app_props.get("CFBundleVersion", "?"),
                                }
                                # Create a nice display name
                                display_name = (
                                    f"{app_info['name']} {app_info['version']} "
                                    f"({app_info['build']})"
                                )
                            except Exception:
                                pass

                        item = XcodeItem(
                            path=path,
                            name=display_name,
                            item_type=XcodeItemType.ARCHIVE,
                            size=size,
                            last_modified=mtime,
                            platform=None,
                            version=None,
                            build=None,
                            is_latest=False,
                            app_info=app_info,
                        )
                        results.items.append(item)

                        if progress_callback:
                            progress_callback(
                                len(results.items), f"Archive: {display_name}"
                            )

                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{archive_entry.path}: {e}")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{archives_dir}: {e}")

    def _scan_simulator_runtimes(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan for simulator runtimes using xcrun simctl."""
        import re

        # Try to get runtime list from simctl
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "runtime", "list", "-v"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # simctl not available or failed
                results.scan_errors.append(
                    "Could not list simulator runtimes (xcrun simctl failed)"
                )
                return

            output = result.stdout
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            results.scan_errors.append(f"Could not run xcrun simctl: {e}")
            return

        # Parse the output to extract runtime info
        # Example lines:
        # iOS 26.2 (23C54) - 5731A96A-F7E6-4DFD-85B1-073AF85985AC
        #     Size: 7.8G
        #     Deletable: YES

        # Track versions per platform for marking latest
        platform_versions: dict[str, list[tuple[tuple[int, ...], int]]] = {}

        current_runtime: dict | None = None
        current_platform: str | None = None

        for line in output.split("\n"):
            line = line.strip()

            # Match runtime header: "iOS 26.2 (23C54) - UUID"
            runtime_match = re.match(
                r"^(\w+)\s+([\d.]+)\s+\(([^)]+)\)\s+-\s+([A-F0-9-]+)$", line
            )
            if runtime_match:
                # Save previous runtime if exists
                if current_runtime and current_runtime.get("deletable"):
                    self._add_runtime_item(
                        results, current_runtime, platform_versions, progress_callback
                    )

                platform = runtime_match.group(1)  # iOS, tvOS, watchOS
                version_str = runtime_match.group(2)  # 26.2
                build = runtime_match.group(3)  # 23C54
                uuid = runtime_match.group(4)

                # Parse version
                try:
                    version = tuple(int(v) for v in version_str.split("."))
                except ValueError:
                    version = None

                current_platform = platform
                current_runtime = {
                    "platform": platform,
                    "version": version,
                    "version_str": version_str,
                    "build": build,
                    "uuid": uuid,
                    "size": 0,
                    "deletable": False,
                    "path": None,
                }
                continue

            if current_runtime:
                # Parse Size: 7.8G
                size_match = re.match(r"Size:\s+([\d.]+)([KMGT]?)B?", line)
                if size_match:
                    size_num = float(size_match.group(1))
                    size_unit = size_match.group(2)
                    multipliers = {
                        "": 1,
                        "K": 1024,
                        "M": 1024**2,
                        "G": 1024**3,
                        "T": 1024**4,
                    }
                    current_runtime["size"] = int(
                        size_num * multipliers.get(size_unit, 1)
                    )
                    continue

                # Parse Deletable: YES/NO
                if line.startswith("Deletable:"):
                    current_runtime["deletable"] = "YES" in line
                    continue

                # Parse Mount Path
                if line.startswith("Mount Path:"):
                    current_runtime["path"] = line.split(":", 1)[1].strip()
                    continue

        # Don't forget the last runtime
        if current_runtime and current_runtime.get("deletable"):
            self._add_runtime_item(
                results, current_runtime, platform_versions, progress_callback
            )

        # Mark latest versions per platform
        for platform_name, versions in platform_versions.items():
            if not versions:
                continue
            # Find the maximum version
            latest_version = max(versions, key=lambda x: x[0])[0]
            # Mark all items with this version as latest
            for item in results.items:
                if (
                    item.item_type == XcodeItemType.SIMULATOR_RUNTIME
                    and item.platform == platform_name
                    and item.version == latest_version
                ):
                    item.is_latest = True

    def _add_runtime_item(
        self,
        results: XcodeScanResults,
        runtime: dict,
        platform_versions: dict,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Add a simulator runtime item to results."""
        platform = runtime["platform"]
        version = runtime["version"]
        version_str = runtime["version_str"]
        build = runtime["build"]

        # Display name: "tvOS 16.0 (20J373)"
        display_name = f"{platform} {version_str} ({build})"

        # Track for latest detection
        if version:
            if platform not in platform_versions:
                platform_versions[platform] = []
            platform_versions[platform].append((version, len(results.items)))

        item = XcodeItem(
            path=Path(runtime.get("path") or f"/simctl:{runtime['uuid']}"),
            name=display_name,
            item_type=XcodeItemType.SIMULATOR_RUNTIME,
            size=runtime["size"],
            last_modified=datetime.now(),  # simctl doesn't give us this
            platform=platform,
            version=version,
            build=build,
            is_latest=False,
            app_info={"uuid": runtime["uuid"]},  # Store UUID for deletion
        )
        results.items.append(item)

        if progress_callback:
            progress_callback(len(results.items), f"Runtime: {display_name}")

    def _scan_documentation(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Documentation cache directory."""
        docs_dir = self.home / self.XCODE_PATHS["documentation"]

        if not docs_dir.exists() or not docs_dir.is_dir():
            return

        try:
            size = self._get_directory_size(docs_dir)
            mtime = self._get_directory_mtime(docs_dir)

            # Only add if there's actual content
            if size > 0:
                item = XcodeItem(
                    path=docs_dir,
                    name="Documentation Cache",
                    item_type=XcodeItemType.DOCUMENTATION,
                    size=size,
                    last_modified=mtime,
                    platform=None,
                    version=None,
                    build=None,
                    is_latest=False,
                )
                results.items.append(item)

                if progress_callback:
                    progress_callback(len(results.items), "Documentation Cache")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{docs_dir}: {e}")

    def _scan_device_logs(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Device Logs directory."""
        logs_dir = self.home / self.XCODE_PATHS["device_logs"]

        if not logs_dir.exists() or not logs_dir.is_dir():
            return

        try:
            # Scan per-device log folders
            for entry in os.scandir(logs_dir):
                if not entry.is_dir():
                    continue

                try:
                    path = Path(entry.path)
                    size = self._get_directory_size(path)
                    mtime = self._get_directory_mtime(path)

                    # Only add if there's actual content
                    if size > 0:
                        item = XcodeItem(
                            path=path,
                            name=f"Device Logs: {entry.name}",
                            item_type=XcodeItemType.DEVICE_LOGS,
                            size=size,
                            last_modified=mtime,
                            platform=None,
                            version=None,
                            build=None,
                            is_latest=False,
                        )
                        results.items.append(item)

                        if progress_callback:
                            progress_callback(len(results.items), f"Logs: {entry.name}")

                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{entry.path}: {e}")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{logs_dir}: {e}")


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
