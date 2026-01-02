"""Interactive project selector with keyboard navigation."""

from __future__ import annotations

import sys
from typing import Callable

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

from ..utils import (
    Project,
    LargeFile,
    CacheLocation,
    format_days_ago,
    format_size,
    open_path,
)


class InteractiveSelector:
    """
    Interactive table selector with keyboard navigation.

    Controls:
        - Up/Down or j/k: Navigate
        - Space: Toggle selection
        - Enter: Confirm selection
        - a: Select all
        - n: Select none
        - q/Esc: Cancel
    """

    def __init__(
        self,
        projects: list[Project],
        title: str = "Select projects to delete",
    ) -> None:
        self.projects = projects
        self.title = title
        self.selected: set[int] = set()
        self.cursor: int = 0
        self.cancelled: bool = False

        # Calculate column widths
        self.col_widths = {
            "select": 3,
            "num": 4,
            "name": min(22, max(len(p.name) for p in projects) + 2) if projects else 20,
            "type": 7,
            "size": 9,
            "opened": 13,
            "commit": 13,
        }

    def _get_header(self) -> FormattedText:
        """Generate the header row."""
        w = self.col_widths
        header = (
            f"{'':>{w['select']}} "
            f"{'#':>{w['num']}} "
            f"{'Project':<{w['name']}} "
            f"{'Type':^{w['type']}} "
            f"{'Size':>{w['size']}} "
            f"{'Last Opened':>{w['opened']}} "
            f"{'Last Commit':>{w['commit']}}"
        )
        return FormattedText([("class:header", header)])

    def _get_row(self, idx: int) -> FormattedText:
        """Generate a single row."""
        project = self.projects[idx]
        w = self.col_widths

        is_selected = idx in self.selected
        is_cursor = idx == self.cursor

        # Selection indicator
        select_char = "[x]" if is_selected else "[ ]"

        # Truncate name if needed
        name = project.name
        if len(name) > w["name"] - 2:
            name = name[: w["name"] - 5] + "..."

        # Last opened (most recent of access/modify)
        last_opened_days = min(project.days_since_accessed, project.days_since_modified)
        last_opened = format_days_ago(last_opened_days)

        # Last commit (or N/A if not git)
        if project.is_git_repo and project.days_since_commit is not None:
            last_commit = format_days_ago(project.days_since_commit)
        else:
            last_commit = "—"

        row = (
            f"{select_char:>{w['select']}} "
            f"{idx + 1:>{w['num']}} "
            f"{name:<{w['name']}} "
            f"{project.project_type.value:^{w['type']}} "
            f"{project.size_formatted:>{w['size']}} "
            f"{last_opened:>{w['opened']}} "
            f"{last_commit:>{w['commit']}}"
        )

        # Style based on state
        if is_cursor and is_selected:
            style = "class:cursor-selected"
        elif is_cursor:
            style = "class:cursor"
        elif is_selected:
            style = "class:selected"
        else:
            style = "class:normal"

        return FormattedText([(style, row)])

    def _get_content(self) -> FormattedText:
        """Generate the full table content."""
        lines = []

        # Title
        lines.append(("class:title", f"\n  {self.title}\n\n"))

        # Instructions
        lines.append(
            (
                "class:help",
                "  [↑/↓] Navigate  [Space] Toggle  [Enter] Confirm  [a] All  [n] None  [q] Cancel\n\n",
            )
        )

        # Header
        lines.append(("class:header", "  "))
        lines.extend(self._get_header())
        lines.append(("", "\n"))
        lines.append(("class:header", "  " + "─" * 80 + "\n"))

        # Rows
        for idx in range(len(self.projects)):
            lines.append(("", "  "))
            lines.extend(self._get_row(idx))
            lines.append(("", "\n"))

        # Footer with selection info
        selected_count = len(self.selected)
        selected_size = sum(self.projects[i].total_size for i in self.selected)
        lines.append(("", "\n"))
        lines.append(
            (
                "class:footer",
                f"  Selected: {selected_count} projects ({format_size(selected_size)})\n",
            )
        )

        return FormattedText(lines)

    def run(self) -> list[Project]:
        """
        Run the interactive selector.

        Returns:
            List of selected projects, or empty list if cancelled.
        """
        if not self.projects:
            return []

        # Key bindings
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def move_up(event):
            self.cursor = max(0, self.cursor - 1)

        @kb.add("down")
        @kb.add("j")
        def move_down(event):
            self.cursor = min(len(self.projects) - 1, self.cursor + 1)

        @kb.add("space")
        def toggle_selection(event):
            if self.cursor in self.selected:
                self.selected.discard(self.cursor)
            else:
                self.selected.add(self.cursor)

        @kb.add("enter")
        def confirm(event):
            event.app.exit()

        @kb.add("a")
        def select_all(event):
            self.selected = set(range(len(self.projects)))

        @kb.add("n")
        def select_none(event):
            self.selected.clear()

        @kb.add("q")
        @kb.add("escape")
        def cancel(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()

        @kb.add("c-c")
        def ctrl_c(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()
            raise KeyboardInterrupt()

        # Styles
        style = Style.from_dict(
            {
                "title": "bold cyan",
                "help": "dim",
                "header": "bold magenta",
                "normal": "",
                "selected": "green",
                "cursor": "reverse",
                "cursor-selected": "reverse green",
                "footer": "bold",
            }
        )

        # Create control that re-renders on each key press
        control = FormattedTextControl(
            text=self._get_content,
            focusable=True,
        )

        # Layout
        layout = Layout(
            HSplit(
                [
                    Window(content=control, wrap_lines=False),
                ]
            )
        )

        # Application
        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=True,
        )

        # Run the app
        app.run()

        if self.cancelled:
            return []

        return [self.projects[i] for i in sorted(self.selected)]


def select_projects_interactive(
    projects: list[Project],
    title: str = "Select projects to delete",
) -> list[Project]:
    """
    Display interactive project selector and return selected projects.

    Args:
        projects: List of projects to choose from
        title: Title to display above the table

    Returns:
        List of selected projects, or empty list if cancelled
    """
    if not projects:
        return []

    selector = InteractiveSelector(projects, title)
    return selector.run()


class LargeFileSelector:
    """
    Interactive large file selector with keyboard navigation.

    Controls:
        - Up/Down or j/k: Navigate
        - Space: Toggle selection
        - Enter: Confirm selection
        - a: Select all
        - n: Select none
        - q/Esc: Cancel
    """

    def __init__(
        self,
        files: list[LargeFile],
        title: str = "Select files to delete",
    ) -> None:
        self.files = files
        self.title = title
        self.selected: set[int] = set()
        self.cursor: int = 0
        self.cancelled: bool = False

        # Calculate column widths
        self.col_widths = {
            "select": 3,
            "num": 4,
            "name": min(30, max(len(f.name) for f in files) + 2) if files else 25,
            "path": 30,
            "size": 10,
            "ext": 6,
            "modified": 13,
        }

    def _get_header(self) -> FormattedText:
        """Generate the header row."""
        w = self.col_widths
        header = (
            f"{'':>{w['select']}} "
            f"{'#':>{w['num']}} "
            f"{'File':<{w['name']}} "
            f"{'Directory':<{w['path']}} "
            f"{'Size':>{w['size']}} "
            f"{'Type':^{w['ext']}} "
            f"{'Modified':>{w['modified']}}"
        )
        return FormattedText([("class:header", header)])

    def _get_row(self, idx: int) -> FormattedText:
        """Generate a single row."""
        file = self.files[idx]
        w = self.col_widths

        is_selected = idx in self.selected
        is_cursor = idx == self.cursor

        # Selection indicator
        select_char = "[x]" if is_selected else "[ ]"

        # Truncate name if needed
        name = file.name
        if len(name) > w["name"] - 2:
            name = name[: w["name"] - 5] + "..."

        # Get parent directory and truncate if needed
        parent = str(file.path.parent)
        if len(parent) > w["path"] - 2:
            parent = "..." + parent[-(w["path"] - 5) :]

        row = (
            f"{select_char:>{w['select']}} "
            f"{idx + 1:>{w['num']}} "
            f"{name:<{w['name']}} "
            f"{parent:<{w['path']}} "
            f"{file.size_formatted:>{w['size']}} "
            f"{file.extension:^{w['ext']}} "
            f"{format_days_ago(file.days_since_modified):>{w['modified']}}"
        )

        # Style based on state
        if is_cursor and is_selected:
            style = "class:cursor-selected"
        elif is_cursor:
            style = "class:cursor"
        elif is_selected:
            style = "class:selected"
        else:
            style = "class:normal"

        return FormattedText([(style, row)])

    def _get_content(self) -> FormattedText:
        """Generate the full table content."""
        lines = []

        # Title
        lines.append(("class:title", f"\n  {self.title}\n\n"))

        # Instructions
        lines.append(
            (
                "class:help",
                "  [↑/↓] Navigate  [Space] Toggle  [Enter] Confirm  [a] All  [n] None  [q] Cancel\n\n",
            )
        )

        # Header
        lines.append(("class:header", "  "))
        lines.extend(self._get_header())
        lines.append(("", "\n"))
        lines.append(("class:header", "  " + "─" * 105 + "\n"))

        # Rows (limit to 30 for display)
        display_count = min(len(self.files), 30)
        for idx in range(display_count):
            lines.append(("", "  "))
            lines.extend(self._get_row(idx))
            lines.append(("", "\n"))

        if len(self.files) > 30:
            lines.append(
                ("class:dim", f"  ... and {len(self.files) - 30} more files\n")
            )

        # Footer with selection info
        selected_count = len(self.selected)
        selected_size = sum(self.files[i].size for i in self.selected)
        lines.append(("", "\n"))
        lines.append(
            (
                "class:footer",
                f"  Selected: {selected_count} files ({format_size(selected_size)})\n",
            )
        )

        return FormattedText(lines)

    def run(self) -> list[LargeFile]:
        """
        Run the interactive selector.

        Returns:
            List of selected files, or empty list if cancelled.
        """
        if not self.files:
            return []

        # Key bindings
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def move_up(event):
            self.cursor = max(0, self.cursor - 1)

        @kb.add("down")
        @kb.add("j")
        def move_down(event):
            max_idx = min(len(self.files), 30) - 1
            self.cursor = min(max_idx, self.cursor + 1)

        @kb.add("space")
        def toggle_selection(event):
            if self.cursor in self.selected:
                self.selected.discard(self.cursor)
            else:
                self.selected.add(self.cursor)

        @kb.add("enter")
        def confirm(event):
            event.app.exit()

        @kb.add("a")
        def select_all(event):
            self.selected = set(range(min(len(self.files), 30)))

        @kb.add("n")
        def select_none(event):
            self.selected.clear()

        @kb.add("q")
        @kb.add("escape")
        def cancel(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()

        @kb.add("c-c")
        def ctrl_c(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()
            raise KeyboardInterrupt()

        # Styles
        style = Style.from_dict(
            {
                "title": "bold cyan",
                "help": "dim",
                "header": "bold magenta",
                "normal": "",
                "selected": "green",
                "cursor": "reverse",
                "cursor-selected": "reverse green",
                "footer": "bold",
                "dim": "dim",
            }
        )

        # Create control that re-renders on each key press
        control = FormattedTextControl(
            text=self._get_content,
            focusable=True,
        )

        # Layout
        layout = Layout(
            HSplit(
                [
                    Window(content=control, wrap_lines=False),
                ]
            )
        )

        # Application
        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=True,
        )

        # Run the app
        app.run()

        if self.cancelled:
            return []

        return [self.files[i] for i in sorted(self.selected)]


def select_files_interactive(
    files: list[LargeFile],
    title: str = "Select files to delete",
) -> list[LargeFile]:
    """
    Display interactive file selector and return selected files.

    Args:
        files: List of files to choose from
        title: Title to display above the table

    Returns:
        List of selected files, or empty list if cancelled
    """
    if not files:
        return []

    selector = LargeFileSelector(files, title)
    return selector.run()


class CacheSelector:
    """
    Interactive cache selector with keyboard navigation.

    Controls:
        - Up/Down or j/k: Navigate
        - Space: Toggle selection
        - Enter: Confirm selection
        - o: Open cache directory in file manager
        - a: Select all
        - n: Select none
        - q/Esc: Cancel
    """

    def __init__(
        self,
        caches: list[CacheLocation],
        title: str = "Select caches to clear",
    ) -> None:
        self.caches = caches
        self.title = title
        self.selected: set[int] = set()
        self.cursor: int = 0
        self.cancelled: bool = False
        self.status_message: str = ""  # For showing open/error messages

        # Calculate column widths
        self.col_widths = {
            "select": 3,
            "num": 4,
            "name": min(28, max(len(c.name) for c in caches) + 2) if caches else 25,
            "category": 16,
            "size": 10,
            "files": 10,
            "modified": 13,
        }

    def _get_header(self) -> FormattedText:
        """Generate the header row."""
        w = self.col_widths
        header = (
            f"{'':>{w['select']}} "
            f"{'#':>{w['num']}} "
            f"{'Cache':<{w['name']}} "
            f"{'Category':<{w['category']}} "
            f"{'Size':>{w['size']}} "
            f"{'Files':>{w['files']}} "
            f"{'Modified':>{w['modified']}}"
        )
        return FormattedText([("class:header", header)])

    def _get_row(self, idx: int) -> FormattedText:
        """Generate a single row."""
        cache = self.caches[idx]
        w = self.col_widths

        is_selected = idx in self.selected
        is_cursor = idx == self.cursor

        # Selection indicator
        select_char = "[x]" if is_selected else "[ ]"

        # Truncate name if needed
        name = cache.name
        if len(name) > w["name"] - 2:
            name = name[: w["name"] - 5] + "..."

        # Format file count
        file_count = f"{cache.file_count:,}"

        row = (
            f"{select_char:>{w['select']}} "
            f"{idx + 1:>{w['num']}} "
            f"{name:<{w['name']}} "
            f"{cache.category.value:<{w['category']}} "
            f"{cache.size_formatted:>{w['size']}} "
            f"{file_count:>{w['files']}} "
            f"{format_days_ago(cache.days_since_modified):>{w['modified']}}"
        )

        # Style based on state
        if is_cursor and is_selected:
            style = "class:cursor-selected"
        elif is_cursor:
            style = "class:cursor"
        elif is_selected:
            style = "class:selected"
        else:
            style = "class:normal"

        return FormattedText([(style, row)])

    def _get_content(self) -> FormattedText:
        """Generate the full table content."""
        lines = []

        # Title
        lines.append(("class:title", f"\n  {self.title}\n\n"))

        # Instructions
        lines.append(
            (
                "class:help",
                "  [Up/Down] Navigate  [Space] Toggle  [o] Open  [Enter] Confirm  [a] All  [n] None  [q] Cancel\n\n",
            )
        )

        # Header
        lines.append(("class:header", "  "))
        lines.extend(self._get_header())
        lines.append(("", "\n"))
        lines.append(("class:header", "  " + "-" * 95 + "\n"))

        # Rows (limit to 25 for display)
        display_count = min(len(self.caches), 25)
        for idx in range(display_count):
            lines.append(("", "  "))
            lines.extend(self._get_row(idx))
            lines.append(("", "\n"))

        if len(self.caches) > 25:
            lines.append(
                ("class:dim", f"  ... and {len(self.caches) - 25} more caches\n")
            )

        # Footer with selection info
        selected_count = len(self.selected)
        selected_size = sum(self.caches[i].size for i in self.selected)
        lines.append(("", "\n"))
        lines.append(
            (
                "class:footer",
                f"  Selected: {selected_count} caches ({format_size(selected_size)})\n",
            )
        )

        # Status message (for open feedback)
        if self.status_message:
            lines.append(("class:status", f"  {self.status_message}\n"))

        return FormattedText(lines)

    def run(self) -> list[CacheLocation]:
        """
        Run the interactive selector.

        Returns:
            List of selected caches, or empty list if cancelled.
        """
        if not self.caches:
            return []

        # Key bindings
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def move_up(event):
            self.cursor = max(0, self.cursor - 1)

        @kb.add("down")
        @kb.add("j")
        def move_down(event):
            max_idx = min(len(self.caches), 25) - 1
            self.cursor = min(max_idx, self.cursor + 1)

        @kb.add("space")
        def toggle_selection(event):
            if self.cursor in self.selected:
                self.selected.discard(self.cursor)
            else:
                self.selected.add(self.cursor)

        @kb.add("enter")
        def confirm(event):
            event.app.exit()

        @kb.add("a")
        def select_all(event):
            self.selected = set(range(min(len(self.caches), 25)))

        @kb.add("n")
        def select_none(event):
            self.selected.clear()

        @kb.add("o")
        def open_cache(event):
            """Open the currently highlighted cache in file manager."""
            if 0 <= self.cursor < len(self.caches):
                cache = self.caches[self.cursor]
                success, msg = open_path(cache.path)
                if success:
                    self.status_message = f"Opened: {cache.name}"
                else:
                    self.status_message = f"Error: {msg}"

        @kb.add("q")
        @kb.add("escape")
        def cancel(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()

        @kb.add("c-c")
        def ctrl_c(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()
            raise KeyboardInterrupt()

        # Styles
        style = Style.from_dict(
            {
                "title": "bold cyan",
                "help": "dim",
                "header": "bold magenta",
                "normal": "",
                "selected": "green",
                "cursor": "reverse",
                "cursor-selected": "reverse green",
                "footer": "bold",
                "dim": "dim",
                "status": "italic cyan",
            }
        )

        # Create control that re-renders on each key press
        control = FormattedTextControl(
            text=self._get_content,
            focusable=True,
        )

        # Layout
        layout = Layout(
            HSplit(
                [
                    Window(content=control, wrap_lines=False),
                ]
            )
        )

        # Application
        app: Application = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=True,
        )

        # Run the app
        app.run()

        if self.cancelled:
            return []

        return [self.caches[i] for i in sorted(self.selected)]


def select_caches_interactive(
    caches: list[CacheLocation],
    title: str = "Select caches to clear",
) -> list[CacheLocation]:
    """
    Display interactive cache selector and return selected caches.

    Args:
        caches: List of caches to choose from
        title: Title to display above the table

    Returns:
        List of selected caches, or empty list if cancelled
    """
    if not caches:
        return []

    selector = CacheSelector(caches, title)
    return selector.run()
