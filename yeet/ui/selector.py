"""Workflow adapters for the shared typed cleanup selector."""

from __future__ import annotations

from typing import TypeVar

from ..models import (
    CacheLocation,
    LeftoverItem,
    Project,
    SelectableItem,
    XcodeItem,
    XcodeItemType,
)
from ..formatting import format_days_ago
from ..filesystem import open_path
from .storage_model import file_storage_group
from .selection import SelectionEngine
from .selection_model import SelectionRow
from .table_schemas import CACHES, FILES, PROJECTS, XCODE

FileItem = TypeVar("FileItem", bound=SelectableItem | LeftoverItem)


class InteractiveSelector(SelectionEngine[Project]):
    def __init__(
        self, projects: list[Project], title: str = "Select projects to delete"
    ) -> None:
        rows = []
        for index, project in enumerate(projects):
            opened = format_days_ago(
                min(project.days_since_accessed, project.days_since_modified)
            )
            commit = (
                format_days_ago(project.days_since_commit)
                if project.is_git_repo and project.days_since_commit is not None
                else "—"
            )
            rows.append(
                SelectionRow(
                    index,
                    project,
                    project.name,
                    project.total_size,
                    project.name,
                    {
                        "name": project.name,
                        "type": project.project_type.value,
                        "size": project.size_formatted,
                        "opened": opened,
                        "commit": commit,
                    },
                )
            )
        super().__init__(rows, PROJECTS, title, "projects")


class DeletionItemSelector(SelectionEngine[FileItem]):
    def __init__(
        self, files: list[FileItem], title: str = "Select files to delete"
    ) -> None:
        rows = [
            SelectionRow(
                index,
                item,
                item.name,
                item.size,
                file_storage_group(item),
                {
                    "name": item.name,
                    "path": str(item.path.parent),
                    "size": item.size_formatted,
                    "type": item.app_hint or item.source
                    if isinstance(item, LeftoverItem)
                    else item.extension,
                    "modified": format_days_ago(item.days_since_modified),
                },
            )
            for index, item in enumerate(files)
        ]
        super().__init__(rows, FILES, title, "files")


class CacheSelector(SelectionEngine[CacheLocation]):
    def __init__(
        self, caches: list[CacheLocation], title: str = "Select caches to clear"
    ) -> None:
        rows = [
            SelectionRow(
                index,
                item,
                item.name,
                item.size,
                item.name,
                {
                    "name": item.name + (" [Xcode]" if item.is_xcode else ""),
                    "category": item.category.value,
                    "size": item.size_formatted,
                    "files": f"{item.file_count:,}",
                    "modified": format_days_ago(item.days_since_modified),
                },
            )
            for index, item in enumerate(caches)
        ]
        super().__init__(
            rows, CACHES, title, "caches", open_item=lambda item: open_path(item.path)
        )


class XcodeSelector(SelectionEngine[XcodeItem]):
    TYPE_ORDER = (
        XcodeItemType.DEVICE_SUPPORT,
        XcodeItemType.DERIVED_DATA,
        XcodeItemType.ARCHIVE,
        XcodeItemType.SIMULATOR_RUNTIME,
        XcodeItemType.SIMULATOR_DEVICE,
        XcodeItemType.DOCUMENTATION,
        XcodeItemType.DEVICE_LOGS,
    )

    def __init__(
        self, items: list[XcodeItem], title: str = "Select Xcode items to delete"
    ) -> None:
        rows = []
        for item_type in self.TYPE_ORDER:
            members = [
                (index, item)
                for index, item in enumerate(items)
                if item.item_type == item_type
            ]
            members.sort(
                key=lambda pair: (pair[1].platform or "", pair[1].version or ()),
                reverse=True,
            )
            for index, item in members:
                rows.append(
                    SelectionRow(
                        index,
                        item,
                        item.name,
                        item.size,
                        item.item_type.value,
                        {
                            "name": item.name,
                            "platform": item.platform or "",
                            "size": item.size_formatted,
                            "modified": format_days_ago(item.days_since_modified),
                            "badge": "[Latest]" if item.is_latest else "",
                        },
                        section=item.item_type.value,
                        bulk_selectable=not item.is_latest,
                        tone="class:latest" if item.is_latest else "",
                        focus_tone="class:cursor-latest" if item.is_latest else "",
                    )
                )
        super().__init__(
            rows,
            XCODE,
            title,
            "items",
            open_item=lambda item: open_path(item.path),
            extra_help="[Latest] marks the newest version; select-all keeps it",
        )
