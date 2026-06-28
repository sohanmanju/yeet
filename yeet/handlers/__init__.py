"""Handlers for yeet CLI workflows."""

from .common import delete_item
from .history import handle_history
from .projects import handle_stale_projects
from .files import handle_large_files
from .caches import handle_cache_scan
from .purge import handle_purge
from .installer import handle_installer_cleanup
from .leftovers import handle_leftovers_cleanup
from .xcode import handle_xcode_cleanup
from .explorer import handle_disk_explorer, export_disk_scan

__all__ = [
    "delete_item",
    "handle_history",
    "handle_stale_projects",
    "handle_large_files",
    "handle_cache_scan",
    "handle_purge",
    "handle_installer_cleanup",
    "handle_leftovers_cleanup",
    "handle_xcode_cleanup",
    "handle_disk_explorer",
    "export_disk_scan",
]
