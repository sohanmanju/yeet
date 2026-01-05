"""Interactive prompts for user input."""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.panel import Panel

from ..utils import Project, format_size, validate_directory


class PathCompleter(Completer):
    """
    Autocomplete completer for filesystem paths.

    Shows directory suggestions as user types, with dropdown menu.
    """

    def __init__(self, only_directories: bool = True) -> None:
        self.only_directories = only_directories

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Expand ~ to home directory
        if text.startswith("~"):
            text = os.path.expanduser(text)

        # Handle empty input
        if not text:
            text = "/"

        # Determine the directory to list and the prefix to match
        if os.path.isdir(text):
            # User typed a complete directory path
            search_dir = text
            prefix = ""
        else:
            # User is typing a partial name
            search_dir = os.path.dirname(text) or "."
            prefix = os.path.basename(text).lower()

        # Expand to absolute path for listing
        try:
            search_dir = os.path.abspath(search_dir)

            if not os.path.isdir(search_dir):
                return

            entries = []
            try:
                with os.scandir(search_dir) as it:
                    for entry in it:
                        try:
                            name = entry.name

                            # Skip hidden files/dirs
                            if name.startswith("."):
                                continue

                            # Filter by type if needed
                            if self.only_directories and not entry.is_dir():
                                continue

                            # Match prefix (case-insensitive)
                            if prefix and not name.lower().startswith(prefix):
                                continue

                            entries.append((name, entry.is_dir()))
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                return

            # Sort directories first, then alphabetically
            entries.sort(key=lambda x: (not x[1], x[0].lower()))

            for name, is_dir in entries[:50]:  # Limit to 50 suggestions
                # Calculate the completion text
                if os.path.isdir(document.text_before_cursor):
                    # Complete from current position
                    completion = name + ("/" if is_dir else "")
                    start_position = 0
                else:
                    # Replace the partial name
                    completion = name + ("/" if is_dir else "")
                    start_position = -len(prefix)

                display = f"{name}/" if is_dir else name

                yield Completion(
                    completion,
                    start_position=start_position,
                    display=display,
                    display_meta="dir" if is_dir else "file",
                )
        except Exception:
            return


# Style for the autocomplete dropdown
PROMPT_STYLE = Style.from_dict(
    {
        "completion-menu.completion": "bg:#333333 #ffffff",
        "completion-menu.completion.current": "bg:#00aa00 #ffffff bold",
        "completion-menu.meta.completion": "bg:#333333 #888888",
        "completion-menu.meta.completion.current": "bg:#00aa00 #ffffff",
        "scrollbar.background": "bg:#333333",
        "scrollbar.button": "bg:#666666",
    }
)


def get_directory_prompt(console: Console) -> Path:
    """
    Prompt user to enter a directory path to scan.

    Features autocomplete with dropdown suggestions.
    Validates the path and loops until a valid directory is provided.
    """
    console.print()
    console.print("[dim]Start typing a path - autocomplete suggestions will appear.[/]")
    console.print(
        "[dim]Use Tab to complete, arrow keys to navigate, Enter to select.[/]"
    )
    console.print()

    completer = PathCompleter(only_directories=True)
    default_path = str(Path.home())

    while True:
        try:
            path_str = prompt(
                "Enter directory to scan: ",
                completer=completer,
                complete_while_typing=True,
                style=PROMPT_STYLE,
                default=default_path,
            )
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt()

        path_str = path_str.strip()
        if not path_str:
            path_str = default_path

        is_valid, result = validate_directory(path_str)

        if is_valid:
            assert isinstance(result, Path)
            console.print(f"[green]Scanning:[/] {result}")
            return result
        else:
            console.print(f"[red]Error:[/] {result}")
            console.print()


def confirm_deletion(
    console: Console,
    projects: list[Project],
    use_trash: bool = False,
) -> bool:
    """
    Show summary and confirm deletion.

    Args:
        console: Rich console for output
        projects: List of projects to delete
        use_trash: If True, items will be moved to trash instead of permanent delete

    Returns True if user confirms, False otherwise.
    """
    total_size = sum(p.total_size for p in projects)

    action_verb = "move to trash" if use_trash else "delete"

    console.print()
    console.print(
        Panel(
            f"[bold red]About to {action_verb} {len(projects)} project(s):[/]\n\n"
            + "\n".join(f"  - {p.name} ({p.size_formatted})" for p in projects[:10])
            + (f"\n  ... and {len(projects) - 10} more" if len(projects) > 10 else "")
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]",
            title="Deletion Summary",
            border_style="red",
        )
    )
    console.print()

    confirm_msg = (
        "[bold red]Are you sure you want to move these projects to trash?[/]"
        if use_trash
        else "[bold red]Are you sure you want to delete these projects permanently?[/]"
    )

    return Confirm.ask(
        confirm_msg,
        default=False,
        console=console,
    )


def confirm_continue(console: Console) -> bool:
    """Ask if user wants to continue with another scan."""
    console.print()
    return Confirm.ask(
        "[bold]Would you like to scan another directory?[/]",
        default=False,
        console=console,
    )
