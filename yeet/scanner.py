"""Project-level scanner for finding coding projects."""

from __future__ import annotations

import os
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

import platform

from .utils import (
    DAYS_SINCE_ACCESS,
    DAYS_SINCE_COMMIT,
    DEFAULT_LARGE_FILE_MB,
    PROJECT_MARKERS,
    SKIP_FOR_SIZE,
    CacheCategory,
    CacheLocation,
    CacheScanResults,
    LargeFile,
    LargeFileScanResults,
    Project,
    ProjectType,
    ScanResults,
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

                    cache = CacheLocation(
                        path=path,
                        name=name,
                        category=category,
                        size=size,
                        file_count=file_count,
                        last_modified=last_modified,
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
