"""Compatibility imports; internal code uses each feature's owning module."""

from .models import (
    DAYS_SINCE_ACCESS as DAYS_SINCE_ACCESS,
    DAYS_SINCE_COMMIT as DAYS_SINCE_COMMIT,
    DEFAULT_LARGE_FILE_MB as DEFAULT_LARGE_FILE_MB,
    ProjectType as ProjectType,
    Project as Project,
    LargeFile as LargeFile,
    SelectableItem as SelectableItem,
    ScanResults as ScanResults,
    LargeFileScanResults as LargeFileScanResults,
    PurgeArtifact as PurgeArtifact,
    PurgeScanResults as PurgeScanResults,
    InstallerItem as InstallerItem,
    InstallerScanResults as InstallerScanResults,
    LeftoverItem as LeftoverItem,
    LeftoverScanResults as LeftoverScanResults,
    CacheCategory as CacheCategory,
    XcodeItemType as XcodeItemType,
    CacheLocation as CacheLocation,
    XcodeItem as XcodeItem,
    XcodeScanResults as XcodeScanResults,
    SIZE_LOADING as SIZE_LOADING,
    DiskItem as DiskItem,
    CacheScanResults as CacheScanResults,
)

from .formatting import (
    format_size as format_size,
    format_days_ago as format_days_ago,
    parse_xcode_version as parse_xcode_version,
)

from .filesystem import (
    delete_file as delete_file,
    delete_directory as delete_directory,
    trash_available as trash_available,
    move_to_trash as move_to_trash,
    _trash_macos as _trash_macos,
    _trash_linux as _trash_linux,
    _trash_windows as _trash_windows,
    validate_directory as validate_directory,
    is_macos as is_macos,
    open_path as open_path,
)

from .project_rules import (
    PROJECT_MARKERS as PROJECT_MARKERS,
    SKIP_FOR_SIZE as SKIP_FOR_SIZE,
)
