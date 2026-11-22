"""Stable data exchanged by scanners and cleanup workflows."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol
from .formatting import format_size

DAYS_SINCE_ACCESS = 90

DAYS_SINCE_COMMIT = 180

DEFAULT_LARGE_FILE_MB = 25


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
    def size(self) -> int:
        return self.total_size

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
        return (datetime.now() - self.last_activity).days

    @property
    def size_formatted(self) -> str:
        """Human-readable project size."""
        return format_size(self.total_size)

    @property
    def last_activity(self) -> datetime:
        return self._latest_activity()[0]

    @property
    def activity_type(self) -> str:
        return self._latest_activity()[1]

    def _latest_activity(self) -> tuple[datetime, str]:
        activities = [(self.last_modified, "modified"), (self.last_accessed, "opened")]
        if self.last_commit_date is not None:
            activities.append((self.last_commit_date, "commit"))
        return max(activities, key=lambda activity: activity[0])


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


class CleanupItem(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def size(self) -> int: ...


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

    total_projects_scanned: int = 0
    total_size_scanned: int = 0
    scan_errors: list[str] = field(default_factory=list)

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

    total_files_scanned: int = 0
    total_dirs_scanned: int = 0
    scan_errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        """Total size of all large files."""
        return sum(f.size for f in self.files)


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
    name: str
    category: CacheCategory
    size: int
    file_count: int
    last_modified: datetime
    is_xcode: bool = False
    delete_contents_only: bool = False

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
    name: str
    item_type: XcodeItemType
    size: int
    last_modified: datetime
    platform: str | None = None
    version: tuple[int, ...] | None = None
    build: str | None = None
    is_latest: bool = False
    app_info: dict | None = None

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


SIZE_LOADING = -1


@dataclass(slots=True)
class DiskItem:
    """Represents a file or directory in the disk explorer."""

    path: Path
    name: str
    size: int
    is_dir: bool
    modified: datetime
    item_count: int | None = None

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
