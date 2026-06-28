"""JSON serialization helpers for scan outputs."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from .utils import (
    CacheLocation,
    CacheScanResults,
    DiskItem,
    InstallerItem,
    InstallerScanResults,
    LeftoverItem,
    LeftoverScanResults,
    LargeFile,
    LargeFileScanResults,
    PurgeArtifact,
    PurgeScanResults,
    Project,
    ScanResults,
    XcodeItem,
    XcodeScanResults,
)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def project_to_dict(project: Project) -> dict:
    return {
        "path": str(project.path),
        "name": project.name,
        "project_type": project.project_type.value,
        "total_size": project.total_size,
        "size_formatted": project.size_formatted,
        "last_modified": _dt(project.last_modified),
        "last_accessed": _dt(project.last_accessed),
        "last_commit_date": _dt(project.last_commit_date),
        "is_git_repo": project.is_git_repo,
        "days_stale": project.days_stale,
        "activity_type": project.activity_type,
    }


def large_file_to_dict(file: LargeFile) -> dict:
    return {
        "path": str(file.path),
        "name": file.name,
        "size": file.size,
        "size_formatted": file.size_formatted,
        "last_accessed": _dt(file.last_accessed),
        "last_modified": _dt(file.last_modified),
        "days_since_accessed": file.days_since_accessed,
        "days_since_modified": file.days_since_modified,
        "extension": file.extension,
    }


def cache_location_to_dict(cache: CacheLocation) -> dict:
    return {
        "path": str(cache.path),
        "name": cache.name,
        "category": cache.category.value,
        "size": cache.size,
        "size_formatted": cache.size_formatted,
        "file_count": cache.file_count,
        "last_modified": _dt(cache.last_modified),
        "days_since_modified": cache.days_since_modified,
        "is_xcode": cache.is_xcode,
    }


def xcode_item_to_dict(item: XcodeItem) -> dict:
    return {
        "path": str(item.path),
        "name": item.name,
        "item_type": item.item_type.value,
        "size": item.size,
        "size_formatted": item.size_formatted,
        "last_modified": _dt(item.last_modified),
        "days_since_modified": item.days_since_modified,
        "platform": item.platform,
        "version": item.version_string,
        "build": item.build,
        "is_latest": item.is_latest,
        "app_info": item.app_info,
    }


def disk_item_to_dict(item: DiskItem) -> dict:
    return {
        "path": str(item.path),
        "name": item.name,
        "size": item.size,
        "size_formatted": item.size_formatted,
        "is_dir": item.is_dir,
        "modified": _dt(item.modified),
        "days_since_modified": item.days_since_modified,
        "item_count": item.item_count,
    }


def purge_artifact_to_dict(item: PurgeArtifact) -> dict:
    return {
        "path": str(item.path),
        "name": item.name,
        "project_root": str(item.project_root),
        "project_name": item.project_name,
        "artifact_type": item.artifact_type,
        "size": item.size,
        "size_formatted": item.size_formatted,
        "last_modified": _dt(item.last_modified),
        "days_since_modified": item.days_since_modified,
    }


def installer_item_to_dict(item: InstallerItem) -> dict:
    return {
        "path": str(item.path),
        "name": item.name,
        "source": item.source,
        "size": item.size,
        "size_formatted": item.size_formatted,
        "last_modified": _dt(item.last_modified),
        "days_since_modified": item.days_since_modified,
        "extension": item.extension,
    }


def leftover_item_to_dict(item: LeftoverItem) -> dict:
    return {
        "path": str(item.path),
        "name": item.name,
        "source": item.source,
        "size": item.size,
        "size_formatted": item.size_formatted,
        "last_modified": _dt(item.last_modified),
        "days_since_modified": item.days_since_modified,
        "app_hint": item.app_hint,
    }


def project_scan_payload(results: ScanResults) -> dict:
    return {
        "total_projects_scanned": results.total_projects_scanned,
        "total_size_scanned": results.total_size_scanned,
        "total_reclaimable_size": results.total_reclaimable_size,
        "scan_errors": results.scan_errors,
        "projects": [project_to_dict(project) for project in results.projects],
    }


def large_file_scan_payload(results: LargeFileScanResults) -> dict:
    return {
        "total_files_scanned": results.total_files_scanned,
        "total_dirs_scanned": results.total_dirs_scanned,
        "total_size": results.total_size,
        "scan_errors": results.scan_errors,
        "files": [large_file_to_dict(file) for file in results.files],
    }


def cache_scan_payload(results: CacheScanResults) -> dict:
    return {
        "total_size": results.total_size,
        "scan_errors": results.scan_errors,
        "caches": [cache_location_to_dict(cache) for cache in results.caches],
    }


def xcode_scan_payload(results: XcodeScanResults) -> dict:
    return {
        "total_size": results.total_size,
        "reclaimable_size": results.reclaimable_size,
        "scan_errors": results.scan_errors,
        "items": [xcode_item_to_dict(item) for item in results.items],
    }


def purge_scan_payload(root_path: Path, results: PurgeScanResults) -> dict:
    return {
        "root_path": str(root_path),
        "total_size": results.total_size,
        "scan_errors": results.scan_errors,
        "artifacts": [purge_artifact_to_dict(item) for item in results.artifacts],
    }


def installer_scan_payload(
    root_path: Path | None, results: InstallerScanResults
) -> dict:
    return {
        "root_path": str(root_path) if root_path is not None else None,
        "total_size": results.total_size,
        "scan_errors": results.scan_errors,
        "items": [installer_item_to_dict(item) for item in results.items],
    }


def leftovers_scan_payload(results: LeftoverScanResults) -> dict:
    return {
        "total_size": results.total_size,
        "scan_errors": results.scan_errors,
        "items": [leftover_item_to_dict(item) for item in results.items],
    }


def disk_scan_payload(root_path: Path, items: list[DiskItem], total_size: int) -> dict:
    return {
        "scan_date": datetime.now().isoformat(),
        "root_path": str(root_path),
        "total_size": total_size,
        "items": [disk_item_to_dict(item) for item in items],
    }


def dump_json(data: dict, *, pretty: bool = True) -> None:
    text = json.dumps(data, indent=2 if pretty else None, sort_keys=pretty)
    sys.stdout.write(text)
    sys.stdout.write("\n")
