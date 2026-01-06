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

from ..utils import (
    delete_directory,
    delete_file,
    move_to_trash,
    trash_available,
)


def delete_item(path: Path, use_trash: bool) -> tuple[bool, str]:
    """
    Delete a file or directory, optionally using system trash.

    Args:
        path: Path to the file or directory to delete
        use_trash: If True and trash is available, move to trash instead of permanent delete

    Returns:
        Tuple of (success, message)
    """
    if use_trash and trash_available():
        return move_to_trash(path)
    else:
        # Fall back to permanent deletion
        if use_trash and not trash_available():
            # Warn user that trash is not available
            pass  # Warning will be shown elsewhere
        if path.is_dir():
            return delete_directory(path)
        else:
            return delete_file(path)


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
