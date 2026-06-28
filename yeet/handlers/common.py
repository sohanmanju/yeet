"""Common utilities for handlers."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

from ..config import Config
from ..history import make_history_entry, write_history_entry
from ..safety import is_protected_path
from ..utils import (
    delete_directory,
    delete_file,
    move_to_trash,
    trash_available,
)


def delete_item(
    path: Path,
    use_trash: bool,
    *,
    dry_run: bool = False,
    config: Config | None = None,
) -> tuple[bool, str]:
    """
    Delete a file or directory, optionally using system trash.

    Args:
        path: Path to the file or directory to delete
        use_trash: If True and trash is available, move to trash instead of permanent delete

    Returns:
        Tuple of (success, message)
    """
    if is_protected_path(path, config):
        return False, f"Protected path: {path}"

    if dry_run:
        action = "move to trash" if use_trash else "delete"
        return True, f"Dry run: would {action}: {path}"

    if use_trash and trash_available():
        return move_to_trash(path)

    if path.is_dir():
        return delete_directory(path)
    return delete_file(path)


def record_history(
    workflow: str,
    *,
    dry_run: bool,
    status: str,
    selected_count: int = 0,
    deleted_count: int = 0,
    reclaimed_bytes: int = 0,
    scanned_count: int | None = None,
    extra: dict | None = None,
) -> bool:
    """Persist a history entry."""
    entry = make_history_entry(
        workflow,
        dry_run=dry_run,
        status=status,
        selected_count=selected_count,
        deleted_count=deleted_count,
        reclaimed_bytes=reclaimed_bytes,
        scanned_count=scanned_count,
        extra=extra,
    )
    return write_history_entry(entry)


def get_progress_context(console: Console, transient: bool = True) -> Progress:
    """Create a standard progress context for scanning operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=transient,
    )


def get_deletion_progress_context(console: Console) -> Progress:
    """Create a standard progress context for deletion operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def check_trash_availability(console: Console, use_trash: bool) -> bool:
    """
    Check if trash is available and warn if not.

    Returns:
        The effective use_trash value after checking availability.
    """
    if use_trash and not trash_available():
        console.print(
            "[yellow]Warning: Trash not available on this system. "
            "Items will be permanently deleted.[/]"
        )
        return False
    return use_trash
