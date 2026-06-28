"""Utility functions for file size formatting, date helpers, and common operations."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol


# Time thresholds
DAYS_SINCE_ACCESS = 90  # Projects not accessed in 90 days
DAYS_SINCE_COMMIT = 180  # Git projects with no commits in 180 days

# Size thresholds
DEFAULT_LARGE_FILE_MB = 25  # Files larger than 25MB

# Files that indicate a directory is a coding project
PROJECT_MARKERS = frozenset(
    {
        # Git
        ".git",
        # Python
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "Pipfile",
        # JavaScript/Node
        "package.json",
        # Rust
        "Cargo.toml",
        # Go
        "go.mod",
        # Ruby
        "Gemfile",
        # Java/Kotlin
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        # .NET
        "*.csproj",
        "*.sln",
        # PHP
        "composer.json",
        # Swift/iOS
        "Package.swift",
        "*.xcodeproj",
        "*.xcworkspace",
        # Dart/Flutter
        "pubspec.yaml",
    }
)

# Directories to skip when calculating size (heavy deps)
SKIP_FOR_SIZE = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "env",
        "target",
        "build",
        "dist",
        ".next",
        ".nuxt",
        "vendor",
        "Pods",
        ".gradle",
    }
)


class ProjectType(Enum):
    """Type of project detected."""

    GIT = "git"
    NODE = "node"
    PYTHON = "python"
    RUST = "rust"
    GO = "go"
    OTHER = "other"


@dataclass(slots=True)
class Project:
    """Represents a coding project directory."""

    path: Path
    name: str
    project_type: ProjectType
    total_size: int
    last_modified: datetime
    last_accessed: datetime
    last_commit_date: datetime | None = None
    is_git_repo: bool = False

    @property
    def days_since_modified(self) -> int:
        """Days since any file in project was modified."""
        return (datetime.now() - self.last_modified).days

    @property
    def days_since_accessed(self) -> int:
        """Days since any file in project was accessed."""
        return (datetime.now() - self.last_accessed).days

    @property
    def days_since_commit(self) -> int | None:
        """Days since last git commit, or None if not a git repo."""
        if self.last_commit_date is None:
            return None
        return (datetime.now() - self.last_commit_date).days

    @property
    def days_stale(self) -> int:
        """
        Days since last activity.

        Uses the MOST RECENT of:
        - Last file access time
        - Last file modification time
        - Last git commit (if git repo)

        This ensures recently opened projects aren't marked as stale
        even if they haven't been committed.
        """
        # Get most recent activity timestamp
        most_recent = self.last_modified

        if self.last_accessed > most_recent:
            most_recent = self.last_accessed

        if self.last_commit_date is not None and self.last_commit_date > most_recent:
            most_recent = self.last_commit_date

        return (datetime.now() - most_recent).days

    @property
    def size_formatted(self) -> str:
        """Human-readable project size."""
        return format_size(self.total_size)

    @property
    def last_activity(self) -> datetime:
        """Most recent activity date (access, modify, or commit)."""
        most_recent = self.last_modified

        if self.last_accessed > most_recent:
            most_recent = self.last_accessed

        if self.last_commit_date is not None and self.last_commit_date > most_recent:
            most_recent = self.last_commit_date

        return most_recent

    @property
    def activity_type(self) -> str:
        """
        Returns what type of activity determined the staleness.

        Returns one of: "commit", "modified", "opened"
        """
        most_recent = self.last_modified
        activity = "modified"

        if self.last_accessed > most_recent:
            most_recent = self.last_accessed
            activity = "opened"

        if self.last_commit_date is not None and self.last_commit_date > most_recent:
            activity = "commit"

        return activity


@dataclass(slots=True)
class LargeFile:
    """Represents a large file found during scan."""

    path: Path
    name: str
    size: int
    last_accessed: datetime
    last_modified: datetime

    @property
    def size_formatted(self) -> str:
        """Human-readable file size."""
        return format_size(self.size)

    @property
    def days_since_accessed(self) -> int:
        """Days since file was last accessed."""
        return (datetime.now() - self.last_accessed).days

    @property
    def days_since_modified(self) -> int:
        """Days since file was last modified."""
        return (datetime.now() - self.last_modified).days

    @property
    def extension(self) -> str:
        """File extension."""
        return self.path.suffix.lower() or "—"


class SelectableItem(Protocol):
    """Item shape used by deletion selectors and cleanup summaries."""

    path: Path
    name: str
    size: int
    size_formatted: str
    days_since_modified: int
    extension: str


@dataclass
class ScanResults:
    """Container for project scan results."""

    projects: list[Project] = field(default_factory=list)

    # Statistics
    total_projects_scanned: int = 0
    total_size_scanned: int = 0
    scan_errors: list[str] = field(default_factory=list)

    @property
    def stale_projects(self) -> list[Project]:
        """Get projects sorted by staleness (most stale first)."""
        return sorted(self.projects, key=lambda p: p.days_stale, reverse=True)

    @property
    def large_projects(self) -> list[Project]:
        """Get projects sorted by size (largest first)."""
        return sorted(self.projects, key=lambda p: p.total_size, reverse=True)

    @property
    def total_reclaimable_size(self) -> int:
        """Total size of all projects."""
        return sum(p.total_size for p in self.projects)


@dataclass
class LargeFileScanResults:
    """Container for large file scan results."""

    files: list[LargeFile] = field(default_factory=list)

    # Statistics
    total_files_scanned: int = 0
    total_dirs_scanned: int = 0
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        """Total size of all large files."""
        return sum(f.size for f in self.files)

    @property
    def by_size(self) -> list[LargeFile]:
        """Get files sorted by size (largest first)."""
        return sorted(self.files, key=lambda f: f.size, reverse=True)


@dataclass(slots=True)
class PurgeArtifact:
    """Represents a project artifact directory found during purge scan."""

    path: Path
    name: str
    project_root: Path
    project_name: str
    artifact_type: str
    size: int
    last_modified: datetime

    @property
    def size_formatted(self) -> str:
        return format_size(self.size)

    @property
    def days_since_modified(self) -> int:
        return (datetime.now() - self.last_modified).days

    @property
    def extension(self) -> str:
        return self.artifact_type


@dataclass
class PurgeScanResults:
    """Container for project artifact purge results."""

    artifacts: list[PurgeArtifact] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(artifact.size for artifact in self.artifacts)

    @property
    def by_project(self) -> dict[Path, list[PurgeArtifact]]:
        result: dict[Path, list[PurgeArtifact]] = {}
        for artifact in self.artifacts:
            result.setdefault(artifact.project_root, []).append(artifact)
        return result

    @property
    def by_size(self) -> list[PurgeArtifact]:
        return sorted(self.artifacts, key=lambda a: a.size, reverse=True)


@dataclass(slots=True)
class InstallerItem:
    """Represents a downloaded installer file or bundle."""

    path: Path
    name: str
    source: str
    size: int
    last_modified: datetime
    extension: str

    @property
    def size_formatted(self) -> str:
        return format_size(self.size)

    @property
    def days_since_modified(self) -> int:
        return (datetime.now() - self.last_modified).days


@dataclass
class InstallerScanResults:
    """Container for installer cleanup results."""

    items: list[InstallerItem] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    @property
    def by_source(self) -> dict[str, list[InstallerItem]]:
        result: dict[str, list[InstallerItem]] = {}
        for item in self.items:
            result.setdefault(item.source, []).append(item)
        return result

    @property
    def by_size(self) -> list[InstallerItem]:
        return sorted(self.items, key=lambda item: item.size, reverse=True)


@dataclass(slots=True)
class LeftoverItem:
    """Represents leftover app data from an uninstalled app."""

    path: Path
    name: str
    source: str
    size: int
    last_modified: datetime
    app_hint: str

    @property
    def size_formatted(self) -> str:
        return format_size(self.size)

    @property
    def days_since_modified(self) -> int:
        return (datetime.now() - self.last_modified).days


@dataclass
class LeftoverScanResults:
    """Container for leftovers scan results."""

    items: list[LeftoverItem] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    @property
    def by_source(self) -> dict[str, list[LeftoverItem]]:
        result: dict[str, list[LeftoverItem]] = {}
        for item in self.items:
            result.setdefault(item.source, []).append(item)
        return result

    @property
    def by_size(self) -> list[LeftoverItem]:
        return sorted(self.items, key=lambda item: item.size, reverse=True)


class CacheCategory(Enum):
    """Category of cache location."""

    BROWSER = "Browser"
    PACKAGE_MANAGER = "Package Manager"
    BUILD_TOOL = "Build Tool"
    CONTAINER = "Container"
    IDE = "IDE/Editor"
    SYSTEM = "System"
    RUNTIME = "Runtime"
    OTHER = "Other"


class XcodeItemType(Enum):
    """Type of Xcode-related item."""

    DEVICE_SUPPORT = "Device Support"
    DERIVED_DATA = "Derived Data"
    ARCHIVE = "Archive"
    DOCUMENTATION = "Documentation"
    DEVICE_LOGS = "Device Logs"
    SIMULATOR_RUNTIME = "Simulator Runtime"
    SIMULATOR_DEVICE = "Simulator Device"


@dataclass(slots=True)
class CacheLocation:
    """Represents a cache directory found during scan."""

    path: Path
    name: str  # Human-readable name (e.g., "npm cache", "Docker images")
    category: CacheCategory
    size: int
    file_count: int
    last_modified: datetime
    is_xcode: bool = False  # Flag to mark Xcode-related caches

    @property
    def size_formatted(self) -> str:
        """Human-readable size."""
        return format_size(self.size)

    @property
    def days_since_modified(self) -> int:
        """Days since cache was last modified."""
        return (datetime.now() - self.last_modified).days


@dataclass(slots=True)
class XcodeItem:
    """Represents an Xcode-related item (device support, archive, simulator, etc.)."""

    path: Path
    name: str  # Display name (e.g., "iOS 17.0 (21A329)", "MyApp 1.2.3 (45)")
    item_type: XcodeItemType
    size: int
    last_modified: datetime
    platform: str | None = None  # "iOS", "watchOS", "tvOS", "visionOS", etc.
    version: tuple[int, ...] | None = None  # Parsed version tuple (17, 0, 1)
    build: str | None = None  # Build number like "21A329"
    is_latest: bool = False  # Whether this is the latest version (should be kept)
    app_info: dict | None = None  # For archives: app name, version, bundle ID

    @property
    def size_formatted(self) -> str:
        """Human-readable size."""
        return format_size(self.size)

    @property
    def days_since_modified(self) -> int:
        """Days since item was last modified."""
        return (datetime.now() - self.last_modified).days

    @property
    def version_string(self) -> str:
        """Version as display string."""
        if self.version is None:
            return ""
        return ".".join(str(v) for v in self.version)


@dataclass
class XcodeScanResults:
    """Container for Xcode scan results."""

    items: list[XcodeItem] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        """Total size of all Xcode items."""
        return sum(item.size for item in self.items)

    @property
    def reclaimable_size(self) -> int:
        """Size of items that can be safely deleted (not latest)."""
        return sum(item.size for item in self.items if not item.is_latest)

    @property
    def by_type(self) -> dict[XcodeItemType, list[XcodeItem]]:
        """Get items grouped by type."""
        result: dict[XcodeItemType, list[XcodeItem]] = {}
        for item in self.items:
            if item.item_type not in result:
                result[item.item_type] = []
            result[item.item_type].append(item)
        return result

    @property
    def by_size(self) -> list[XcodeItem]:
        """Get items sorted by size (largest first)."""
        return sorted(self.items, key=lambda x: x.size, reverse=True)


# Size constant for loading state
SIZE_LOADING = -1


@dataclass(slots=True)
class DiskItem:
    """Represents a file or directory in the disk explorer."""

    path: Path
    name: str
    size: int  # Bytes, or SIZE_LOADING (-1) if not yet calculated
    is_dir: bool
    modified: datetime
    item_count: int | None = None  # Number of items inside (for directories)

    @property
    def size_formatted(self) -> str:
        """Human-readable size, or 'Scanning...' if loading."""
        if self.size == SIZE_LOADING:
            return "Scanning..."
        return format_size(self.size)

    @property
    def is_loading(self) -> bool:
        """Check if size is still being calculated."""
        return self.size == SIZE_LOADING

    @property
    def days_since_modified(self) -> int:
        """Days since item was last modified."""
        return (datetime.now() - self.modified).days


@dataclass
class CacheScanResults:
    """Container for cache scan results."""

    caches: list[CacheLocation] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        """Total size of all caches."""
        return sum(c.size for c in self.caches)

    @property
    def by_size(self) -> list[CacheLocation]:
        """Get caches sorted by size (largest first)."""
        return sorted(self.caches, key=lambda c: c.size, reverse=True)

    @property
    def by_category(self) -> dict[CacheCategory, list[CacheLocation]]:
        """Get caches grouped by category."""
        result: dict[CacheCategory, list[CacheLocation]] = {}
        for cache in self.caches:
            if cache.category not in result:
                result[cache.category] = []
            result[cache.category].append(cache)
        return result


def format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    if size_bytes < 0:
        return "0 B"

    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size:.1f} PB"


def format_days_ago(days: int | None) -> str:
    """Format days as relative time string."""
    if days is None:
        return "Never"
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years > 1 else ''} ago"


def delete_file(path: Path) -> tuple[bool, str]:
    """Delete a file and return success status with message."""
    try:
        if path.is_file():
            path.unlink()
            return True, f"Deleted: {path}"
        return False, f"Not a file: {path}"
    except PermissionError:
        return False, f"Permission denied: {path}"
    except OSError as e:
        return False, f"Error deleting {path}: {e}"


def delete_directory(path: Path) -> tuple[bool, str]:
    """Delete a directory and all its contents."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
            return True, f"Deleted directory: {path}"
        return False, f"Not a directory: {path}"
    except PermissionError:
        return False, f"Permission denied: {path}"
    except OSError as e:
        return False, f"Error deleting {path}: {e}"


def trash_available() -> bool:
    """
    Check if system trash is supported on the current platform.

    Returns:
        True if trash functionality is available, False otherwise.
    """
    system = platform.system().lower()

    if system == "darwin":
        # macOS always has Trash via osascript
        return True
    elif system == "linux":
        # Linux uses freedesktop.org trash spec
        # We can create the trash dirs if needed
        return True
    elif system == "windows":
        # Windows requires send2trash library
        try:
            import send2trash  # noqa: F401

            return True
        except ImportError:
            return False
    else:
        return False


def move_to_trash(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to the system trash instead of permanent deletion.

    This function provides cross-platform trash support:
    - macOS: Uses osascript to move to Trash (most reliable method)
    - Linux: Moves to ~/.local/share/Trash/ following freedesktop.org spec
    - Windows: Uses send2trash library if available, otherwise falls back
      to permanent deletion with a warning

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message) where success is True if the item
        was moved to trash successfully.
    """
    try:
        path = path.resolve()

        if not path.exists():
            return False, f"Path does not exist: {path}"

        system = platform.system().lower()

        if system == "darwin":
            return _trash_macos(path)
        elif system == "linux":
            return _trash_linux(path)
        elif system == "windows":
            return _trash_windows(path)
        else:
            return False, f"Unsupported platform for trash: {system}"

    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        return False, f"Error moving to trash: {e}"


def _trash_macos(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to Trash on macOS using osascript.

    This is the most reliable method as it properly handles:
    - Trash metadata (.DS_Store, etc.)
    - "Put Back" functionality
    - Name conflicts (automatically appends numbers)

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message)
    """
    try:
        # Use osascript to move to Trash via Finder
        # This is more reliable than moving to ~/.Trash directly
        # as it handles all the metadata and "Put Back" functionality
        script = f'''
            tell application "Finder"
                delete POSIX file "{path}"
            end tell
        '''
        # Use a longer timeout (120s) for large directories
        # Finder can be slow when trashing many files
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return True, f"Moved to Trash: {path}"
        else:
            # If osascript fails, provide the error message
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            # Check for common permission errors
            if (
                "permission" in error_msg.lower()
                or "not have permission" in error_msg.lower()
            ):
                return False, f"Permission denied (some items may be protected): {path}"
            return False, f"Failed to move to Trash: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, f"Timeout moving to Trash (directory may be too large): {path}"
    except FileNotFoundError:
        return False, "osascript command not found"
    except Exception as e:
        return False, f"Error moving to Trash: {e}"


def _trash_linux(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to Trash on Linux.

    Follows the freedesktop.org Trash specification:
    - Files go to ~/.local/share/Trash/files/
    - Info files go to ~/.local/share/Trash/info/

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message)
    """
    try:
        trash_base = Path.home() / ".local" / "share" / "Trash"
        trash_files = trash_base / "files"
        trash_info = trash_base / "info"

        # Create trash directories if they don't exist
        trash_files.mkdir(parents=True, exist_ok=True)
        trash_info.mkdir(parents=True, exist_ok=True)

        # Generate unique name to avoid conflicts
        trash_name = path.name
        trash_path = trash_files / trash_name
        info_path = trash_info / f"{trash_name}.trashinfo"

        # Handle name conflicts by appending timestamp
        if trash_path.exists() or info_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            base_name = path.stem if path.is_file() else path.name
            suffix = path.suffix if path.is_file() else ""
            trash_name = f"{base_name}_{timestamp}{suffix}"
            trash_path = trash_files / trash_name
            info_path = trash_info / f"{trash_name}.trashinfo"

        # Create the .trashinfo file (freedesktop.org spec)
        deletion_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        # URL-encode the path for the trashinfo file
        from urllib.parse import quote

        encoded_path = quote(str(path), safe="/")
        info_content = f"""[Trash Info]
Path={encoded_path}
DeletionDate={deletion_date}
"""

        # Write info file first
        info_path.write_text(info_content)

        # Move the file/directory to trash
        try:
            shutil.move(str(path), str(trash_path))
        except Exception as e:
            # If move fails, clean up the info file
            info_path.unlink(missing_ok=True)
            raise e

        return True, f"Moved to Trash: {path}"

    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        return False, f"Error moving to Trash: {e}"


def _trash_windows(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to Recycle Bin on Windows.

    Uses the send2trash library if available, otherwise falls back
    to permanent deletion with a warning.

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message)
    """
    try:
        import send2trash

        send2trash.send2trash(str(path))
        return True, f"Moved to Recycle Bin: {path}"
    except ImportError:
        # send2trash not available, fall back to permanent deletion
        if path.is_dir():
            success, msg = delete_directory(path)
        else:
            success, msg = delete_file(path)

        if success:
            return (
                True,
                f"Warning: send2trash not installed, permanently deleted: {path}",
            )
        return success, msg
    except Exception as e:
        return False, f"Error moving to Recycle Bin: {e}"


def validate_directory(path_str: str) -> tuple[bool, Path | str]:
    """Validate that a path is a valid, accessible directory."""
    try:
        path = Path(path_str).expanduser().resolve()

        if not path.exists():
            return False, f"Path does not exist: {path}"

        if not path.is_dir():
            return False, f"Path is not a directory: {path}"

        # Check if we can read the directory
        try:
            next(os.scandir(path), None)
        except PermissionError:
            return False, f"Permission denied: {path}"

        return True, path

    except Exception as e:
        return False, f"Invalid path: {e}"


def parse_xcode_version(version_str: str) -> tuple[tuple[int, ...] | None, str | None]:
    """
    Parse Xcode device support version string.

    Examples:
        "17.0" -> ((17, 0), None)
        "17.0.1 (21B91)" -> ((17, 0, 1), "21B91")
        "17.0 (21A329) arm64e" -> ((17, 0), "21A329")
        "16.4.1 (20E252)" -> ((16, 4, 1), "20E252")

    Returns:
        Tuple of (version_tuple, build_string)
    """
    import re

    # Extract build number in parentheses
    build_match = re.search(r"\(([^)]+)\)", version_str)
    build = build_match.group(1) if build_match else None

    # Extract version numbers (e.g., "17.0.1")
    version_match = re.match(r"(\d+(?:\.\d+)*)", version_str)
    if version_match:
        version_parts = version_match.group(1).split(".")
        version = tuple(int(p) for p in version_parts)
        return version, build

    return None, build


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system().lower() == "darwin"


def open_path(path: Path) -> tuple[bool, str]:
    """
    Open a path in the system file manager.

    - macOS: Opens in Finder
    - Linux: Opens with xdg-open
    - Windows: Opens in Explorer

    Args:
        path: Path to open (file or directory)

    Returns:
        Tuple of (success, message)
    """
    try:
        if not path.exists():
            return False, f"Path does not exist: {path}"

        system = platform.system().lower()

        if system == "darwin":
            # macOS - use 'open' command
            # -R reveals the file in Finder (selects it)
            if path.is_file():
                subprocess.run(["open", "-R", str(path)], check=True)
            else:
                subprocess.run(["open", str(path)], check=True)

        elif system == "linux":
            # Linux - use xdg-open
            subprocess.run(["xdg-open", str(path)], check=True)

        elif system == "windows":
            # Windows - use explorer
            if path.is_file():
                # /select highlights the file in Explorer
                subprocess.run(["explorer", "/select,", str(path)], check=True)
            else:
                subprocess.run(["explorer", str(path)], check=True)

        else:
            return False, f"Unsupported platform: {system}"

        return True, f"Opened: {path}"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to open: {e}"
    except FileNotFoundError:
        return False, "File manager command not found"
    except Exception as e:
        return False, f"Error opening path: {e}"
