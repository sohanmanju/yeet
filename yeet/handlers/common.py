"""Deletion safety and history shared by all cleanup workflows."""

from __future__ import annotations

from pathlib import Path
from ..config import Config
from ..history import make_history_entry, write_history_entry
from ..safety import is_protected_path
from ..filesystem import delete_directory, delete_file, move_to_trash, trash_available


def delete_item(
    path: Path, use_trash: bool, *, config: Config | None = None
) -> tuple[bool, str]:
    """Execute exactly the confirmed operation; never silently fall back to deletion."""
    if is_protected_path(path, config):
        return False, f"Protected path: {path}"
    if use_trash:
        if not trash_available():
            return (
                False,
                "Trash is unavailable. Review and explicitly confirm permanent deletion to proceed.",
            )
        return move_to_trash(path)
    if path.is_dir() and not path.is_symlink():
        return delete_directory(path)
    return delete_file(path)


def record_history(
    workflow: str,
    *,
    status: str,
    selected_count: int = 0,
    deleted_count: int = 0,
    reclaimed_bytes: int = 0,
    scanned_count: int | None = None,
    extra: dict | None = None,
) -> bool:
    return write_history_entry(
        make_history_entry(
            workflow,
            status=status,
            selected_count=selected_count,
            deleted_count=deleted_count,
            reclaimed_bytes=reclaimed_bytes,
            scanned_count=scanned_count,
            extra=extra,
        )
    )


def record_cleanup(workflow, outcomes, use_trash, *, scanned_count=None):
    """Record the same deletion accounting for scanned lists and the explorer."""
    completed_bytes = sum(item.size for item, ok, _ in outcomes if ok)
    return record_history(
        workflow,
        status="completed",
        selected_count=len(outcomes),
        deleted_count=sum(ok for _, ok, _ in outcomes),
        reclaimed_bytes=0 if use_trash else completed_bytes,
        scanned_count=scanned_count,
        extra={
            "use_trash": use_trash,
            "moved_bytes": completed_bytes if use_trash else 0,
        },
    )


def execute_items(items, use_trash, delete, update):
    results = []
    for index, item in enumerate(items):
        update(f"{index + 1}/{len(items)} · {item.path}")
        try:
            ok, message = delete(item, use_trash)
        except Exception as error:
            ok, message = False, str(error)
        results.append((item, ok, message))
    return results
