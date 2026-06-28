"""Interactive disk explorer UI with directory traversal."""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

from ..config import get_config
from ..scanner import DiskExplorer
from ..utils import (
    DiskItem,
    SIZE_LOADING,
    format_size,
    format_days_ago,
    open_path,
)
from . import explorer_render


class DiskExplorerUI:
    """
    Interactive disk explorer with directory traversal.

    Features:
    - Navigate directories by size
    - Select items across directory traversals
    - Lazy loading of directory sizes
    - Breadcrumb navigation
    - Info panel for detailed item information
    - Filter by name or age
    - File type breakdown
    - Bookmarks for quick navigation

    Controls:
        - Up/Down or j/k: Navigate
        - g/G: Go to top/bottom
        - Ctrl+U/Page Up: Move up 10 items
        - Ctrl+D/Page Down: Move down 10 items
        - Enter or l: Open directory
        - Backspace or h: Go to parent
        - Space: Toggle selection
        - d: Delete selected items
        - v: View selection list
        - o: Open in Finder
        - i: Toggle info panel
        - s: Cycle sort mode
        - t: Toggle showing small items
        - e: Show file type breakdown
        - f: Start filter mode
        - ~: Jump to home directory
        - /: Jump to root
        - r: Refresh current directory
        - b: Jump to next bookmark
        - B: Bookmark current directory
        - ?: Show help
        - q: Quit
    """

    def __init__(
        self,
        explorer: DiskExplorer,
        start_path: Path = Path("/"),
    ) -> None:
        """
        Initialize the disk explorer UI.

        Args:
            explorer: DiskExplorer instance for scanning
            start_path: Starting directory path
        """
        self.explorer = explorer
        self._config = get_config()
        self.current_path = start_path
        self.history: deque[Path] = deque(maxlen=100)  # Bounded history
        self.items: list[DiskItem] = []
        self.cursor: int = 0
        self.selected: set[Path] = set()  # Persists across navigation
        self.show_small_items: bool = False
        self.sort_mode: str = "size"  # "size", "name", "modified"
        self.status_message: str = ""
        self.cancelled: bool = False

        # For lazy loading
        self._loading_thread: threading.Thread | None = None
        self._stop_loading = threading.Event()

        # Column widths
        self.col_widths = {
            "select": 3,
            "icon": 2,
            "name": 45,
            "size": 12,
            "modified": 14,
        }

        # Filter state
        self.filter_mode: bool = False
        self.filter_text: str = ""
        self.filtered_items: list[DiskItem] | None = None  # None = no filter active

        # Age filter state
        self.age_filter_mode: bool = False
        self.age_filter_days: int | None = None  # None = no age filter active
        self.age_filter_input: str = ""  # For building the input

        # Extensions overlay state
        self.show_extensions: bool = False

        # Help overlay
        self.show_help: bool = False

        # Info panel state
        self.show_info_panel: bool = False

        # Bookmarks
        self.bookmarks: list[Path] = [Path(path).expanduser() for path in self._config.bookmarks]

        # Quit warning state
        self._quit_warned: bool = False

        # Application reference for triggering refreshes from background thread
        self._app: Application | None = None

    def _scan_current_directory(self) -> None:
        """Scan the current directory and update items list."""
        self.items = self.explorer.scan_directory(
            self.current_path,
            include_small=self.show_small_items,
        )
        self._sort_items()

        # Start lazy loading for directories with unknown sizes
        self._start_lazy_loading()

    def _sort_items(self) -> None:
        """Sort items according to current sort mode."""
        if self.sort_mode == "size":
            # Known sizes first (largest to smallest), then loading
            self.items.sort(
                key=lambda x: (
                    x.size == SIZE_LOADING,
                    -x.size if x.size != SIZE_LOADING else 0,
                )
            )
        elif self.sort_mode == "name":
            self.items.sort(key=lambda x: x.name.lower())
        elif self.sort_mode == "modified":
            self.items.sort(key=lambda x: x.modified, reverse=True)

    def _apply_filter(self) -> None:
        """Apply the current name filter to items."""
        if not self.filter_text:
            self.filtered_items = None
        else:
            pattern = self.filter_text.lower()
            self.filtered_items = [
                item
                for item in self.items
                if pattern in item.name.lower() or pattern in str(item.path).lower()
            ]
        # Re-apply age filter on top if active
        self._apply_age_filter()
        self.cursor = 0

    def _apply_age_filter(self) -> None:
        """Apply the age filter to items."""
        if self.age_filter_days is None:
            return

        # Get the base list to filter (either already name-filtered or all items)
        base_items = (
            self.filtered_items if self.filtered_items is not None else self.items
        )

        # Filter to show only items where days_since_modified >= age_filter_days
        self.filtered_items = [
            item
            for item in base_items
            if item.days_since_modified >= self.age_filter_days
        ]

    def _clear_filter(self) -> None:
        """Clear the active name filter."""
        self.filter_text = ""
        self.filtered_items = None
        # Re-apply age filter if still active
        if self.age_filter_days is not None:
            self._apply_age_filter()
        self.cursor = 0

    def _clear_age_filter(self) -> None:
        """Clear the age filter."""
        self.age_filter_days = None
        self.age_filter_input = ""
        # Re-apply name filter only if active
        if self.filter_text:
            self._apply_filter()
        else:
            self.filtered_items = None
        self.cursor = 0

    def _get_display_items(self) -> list[DiskItem]:
        """Get the items to display (filtered by name and/or age, or all)."""
        return self.filtered_items if self.filtered_items is not None else self.items

    def _is_bookmarked(self, path: Path) -> bool:
        return any(path == bookmark for bookmark in self.bookmarks)

    def _save_bookmarks(self) -> None:
        self._config.bookmarks = [str(path) for path in self.bookmarks]
        self._config.save()

    def _bookmark_current_path(self) -> None:
        if self.current_path not in self.bookmarks:
            self.bookmarks.append(self.current_path)
            self._save_bookmarks()
            self.status_message = f"Bookmarked {self.current_path.name or '/'}"
        else:
            self.status_message = "Already bookmarked"

    def _go_to_next_bookmark(self) -> None:
        if not self.bookmarks:
            self.status_message = "No bookmarks saved"
            return

        current = self.current_path.resolve()
        bookmarks = [bookmark.resolve() for bookmark in self.bookmarks]
        try:
            idx = bookmarks.index(current)
            target = bookmarks[(idx + 1) % len(bookmarks)]
        except ValueError:
            target = bookmarks[0]

        if target.is_dir():
            self.navigate_to(target)
            self.status_message = f"Opened bookmark: {target.name or '/'}"
        else:
            self.status_message = f"Bookmark is not a directory: {target}"

    def _start_lazy_loading(self) -> None:
        """Start background thread to calculate directory sizes using parallel scanning."""
        # Stop any existing loading
        self._stop_loading.set()
        if self._loading_thread and self._loading_thread.is_alive():
            self._loading_thread.join(timeout=0.5)

        self._stop_loading.clear()

        # Find items that need size calculation
        items_to_load = [
            item for item in self.items if item.is_dir and item.size == SIZE_LOADING
        ]

        if not items_to_load:
            return

        # Build a mapping from path to item for quick lookup
        path_to_item = {item.path: item for item in items_to_load}

        # Calculate which items are currently visible (dynamic viewport based on terminal)
        term_height = get_terminal_size().lines
        viewport_size = max(5, term_height - 16)
        total = len(self.items)
        if total <= viewport_size:
            start, end = 0, total
        else:
            half_viewport = viewport_size // 2
            start = max(0, self.cursor - half_viewport)
            end = min(total, start + viewport_size)
            if end - start < viewport_size:
                start = max(0, end - viewport_size)

        # Get visible items that are still loading
        visible_items = [
            item
            for item in self.items[start:end]
            if item.is_dir and item.size == SIZE_LOADING
        ]

        def load_sizes():
            paths = [item.path for item in items_to_load]
            priority_paths = [item.path for item in visible_items]

            def on_size_calculated(path: Path, size: int):
                # Check if we should stop
                if self._stop_loading.is_set():
                    return
                # Find and update the item
                if path in path_to_item:
                    path_to_item[path].size = size
                    # Trigger UI refresh
                    if self._app is not None:
                        self._app.invalidate()

            self.explorer.calculate_sizes_prioritized(
                paths=paths,
                priority_paths=priority_paths,
                callback=on_size_calculated,
                stop_event=self._stop_loading,
            )

        self._loading_thread = threading.Thread(target=load_sizes, daemon=True)
        self._loading_thread.start()

    def _get_breadcrumbs(self, max_width: int = 70) -> FormattedText:
        return explorer_render.get_breadcrumbs(self, max_width=max_width)

    def _get_parent_total_size(self) -> int | None:
        return explorer_render.get_parent_total_size(self)

    def _get_item_info(self, item: DiskItem) -> FormattedText:
        return explorer_render.get_item_info(self, item)

    def _get_header(self) -> FormattedText:
        return explorer_render.get_header(self)

    def _get_row(
        self,
        idx: int,
        display_items: list[DiskItem],
    ) -> FormattedText:
        return explorer_render.get_row(self, idx, display_items)

    def _calculate_extension_stats(self) -> list[tuple[str, int, int]]:
        return explorer_render.calculate_extension_stats(self)

    def _get_extensions_content(self) -> FormattedText:
        return explorer_render.get_extensions_content(self)

    def _get_help_content(self) -> FormattedText:
        return explorer_render.get_help_content(self)

    def _get_content(self) -> FormattedText:
        return explorer_render.get_content(self)

    def navigate_into(self, item: DiskItem) -> None:
        """Navigate into a directory."""
        if not item.is_dir:
            self.status_message = "Cannot open: not a directory"
            return

        self.history.append(self.current_path)
        self.current_path = item.path
        self.cursor = 0
        self._clear_filter()
        self._scan_current_directory()
        self.status_message = ""

    def navigate_back(self) -> None:
        """Navigate to parent directory."""
        if self.history:
            self.current_path = self.history.pop()
        else:
            parent = self.current_path.parent
            if parent != self.current_path:
                self.current_path = parent

        self.cursor = 0
        self._clear_filter()
        self._scan_current_directory()
        self.status_message = ""

    def navigate_to(self, path: Path) -> None:
        """Navigate directly to a specific path."""
        if path.is_dir():
            self.history.append(self.current_path)
            self.current_path = path
            self.cursor = 0
            self._clear_filter()
            self._scan_current_directory()
            self.status_message = ""

    def toggle_selection(self) -> None:
        """Toggle selection of current item."""
        display_items = self._get_display_items()
        if not display_items or self.cursor >= len(display_items):
            return

        item = display_items[self.cursor]
        if item.path in self.selected:
            self.selected.discard(item.path)
        else:
            self.selected.add(item.path)

    def cycle_sort_mode(self) -> None:
        """Cycle through sort modes."""
        modes = ["size", "name", "modified"]
        current_idx = modes.index(self.sort_mode)
        self.sort_mode = modes[(current_idx + 1) % len(modes)]
        self._sort_items()
        self.status_message = f"Sort by: {self.sort_mode}"

    def toggle_small_items(self) -> None:
        """Toggle showing small items."""
        self.show_small_items = not self.show_small_items
        self._scan_current_directory()
        if self.show_small_items:
            self.status_message = "Showing all items"
        else:
            self.status_message = (
                f"Hiding items < {format_size(self.explorer.min_size_bytes)}"
            )

    def refresh(self) -> None:
        """Refresh current directory."""
        self._scan_current_directory()
        self.status_message = "Refreshed"

    def run(self) -> set[Path]:
        """
        Run the interactive explorer.

        Returns:
            Set of paths selected for deletion, or empty set if cancelled.
        """
        # Initial scan
        self._scan_current_directory()

        # Key bindings
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def move_up(event):
            if self.filter_mode or self.age_filter_mode:
                return
            display_items = self._get_display_items()
            if display_items:
                self.cursor = max(0, self.cursor - 1)

        @kb.add("down")
        @kb.add("j")
        def move_down(event):
            if self.filter_mode or self.age_filter_mode:
                return
            display_items = self._get_display_items()
            if display_items:
                self.cursor = min(len(display_items) - 1, self.cursor + 1)

        @kb.add("enter")
        def open_dir_or_apply_filter(event):
            if self.age_filter_mode:
                # Apply age filter and exit age filter mode
                if self.age_filter_input:
                    try:
                        self.age_filter_days = int(self.age_filter_input)
                        self._apply_age_filter()
                        self.status_message = (
                            f"Showing items older than {self.age_filter_days} days"
                        )
                    except ValueError:
                        self.status_message = "Invalid number"
                self.age_filter_mode = False
                self.age_filter_input = ""
                return
            if self.filter_mode:
                # Apply filter and exit filter mode
                self._apply_filter()
                self.filter_mode = False
                return
            display_items = self._get_display_items()
            if display_items and self.cursor < len(display_items):
                item = display_items[self.cursor]
                if item.is_dir:
                    self.navigate_into(item)
                else:
                    self.status_message = "Cannot open: not a directory"

        @kb.add("l")
        def open_dir(event):
            if self.filter_mode:
                # Add 'l' to filter text
                self.filter_text += "l"
                return
            display_items = self._get_display_items()
            if display_items and self.cursor < len(display_items):
                item = display_items[self.cursor]
                if item.is_dir:
                    self.navigate_into(item)
                else:
                    self.status_message = "Cannot open: not a directory"

        @kb.add("backspace")
        def backspace_handler(event):
            if self.age_filter_mode:
                # Delete last character in age filter input
                self.age_filter_input = self.age_filter_input[:-1]
                return
            if self.filter_mode:
                # Delete last character in filter
                self.filter_text = self.filter_text[:-1]
                return
            self.navigate_back()

        @kb.add("h")
        def go_back(event):
            if self.filter_mode:
                # Add 'h' to filter text
                self.filter_text += "h"
                return
            self.navigate_back()

        @kb.add("space")
        def toggle_select(event):
            self.toggle_selection()

        @kb.add("*")
        def select_all_visible(event):
            """Select all visible items."""
            if self.filter_mode or self.age_filter_mode:
                return
            display_items = self._get_display_items()
            for item in display_items:
                self.selected.add(item.path)
            self.status_message = f"Selected {len(display_items)} items"

        @kb.add("u")
        def deselect_all(event):
            """Deselect all items."""
            if self.filter_mode:
                self.filter_text += "u"
                return
            if self.age_filter_mode:
                return
            count = len(self.selected)
            self.selected.clear()
            self.status_message = f"Deselected {count} items"

        @kb.add("s")
        def cycle_sort(event):
            self.cycle_sort_mode()

        @kb.add("t")
        def toggle_small(event):
            self.toggle_small_items()

        @kb.add("r")
        def refresh_dir(event):
            self.refresh()

        @kb.add("b")
        def go_next_bookmark(event):
            if self.filter_mode:
                self.filter_text += "b"
                return
            self._go_to_next_bookmark()

        @kb.add("B")
        def bookmark_current(event):
            if self.filter_mode:
                self.filter_text += "B"
                return
            self._bookmark_current_path()

        @kb.add("o")
        def open_in_finder(event):
            display_items = self._get_display_items()
            if display_items and self.cursor < len(display_items):
                item = display_items[self.cursor]
                success, msg = open_path(item.path)
                self.status_message = msg

        @kb.add("~")
        def go_home(event):
            self.navigate_to(Path.home())

        @kb.add("/")
        def go_root(event):
            self.navigate_to(Path("/"))

        @kb.add("v")
        def view_selection(event):
            if self.selected:
                self._show_selection_view()

        @kb.add("d")
        def delete_selected(event):
            if self.selected:
                event.app.exit(result="delete")

        @kb.add("e")
        def toggle_extensions(event):
            if self.filter_mode:
                self.filter_text += "e"
                return
            if self.age_filter_mode:
                return
            self.show_extensions = not self.show_extensions

        @kb.add("f")
        def start_filter(event):
            if self.filter_mode or self.age_filter_mode:
                if self.filter_mode:
                    self.filter_text += "f"
                return
            self.filter_mode = True
            self.filter_text = ""

        @kb.add("c")
        def clear_filter(event):
            if self.filter_mode:
                self.filter_text += "c"
                return
            if self.age_filter_mode:
                return
            if self.filtered_items is not None or self.filter_text:
                self._clear_filter()
                self.status_message = "Name filter cleared"

        @kb.add("a")
        def start_age_filter(event):
            if self.filter_mode:
                self.filter_text += "a"
                return
            if self.age_filter_mode:
                return
            self.age_filter_mode = True
            self.age_filter_input = ""

        @kb.add("A")
        def clear_age_filter(event):
            if self.filter_mode:
                self.filter_text += "A"
                return
            if self.age_filter_mode:
                return
            if self.age_filter_days is not None:
                self._clear_age_filter()
                self.status_message = "Age filter cleared"

        @kb.add("g")
        def go_to_top(event):
            """Go to top of list."""
            if self.filter_mode:
                self.filter_text += "g"
                return
            if self.age_filter_mode:
                return
            self.cursor = 0

        @kb.add("G")
        def go_to_bottom(event):
            """Go to bottom of list."""
            if self.filter_mode:
                self.filter_text += "G"
                return
            if self.age_filter_mode:
                return
            display_items = self._get_display_items()
            if display_items:
                self.cursor = len(display_items) - 1

        @kb.add("c-u")
        @kb.add("pageup")
        def page_up(event):
            """Move cursor up 10 items."""
            self.cursor = max(0, self.cursor - 10)

        @kb.add("c-d")
        @kb.add("pagedown")
        def page_down(event):
            """Move cursor down 10 items."""
            display_items = self._get_display_items()
            if display_items:
                self.cursor = min(len(display_items) - 1, self.cursor + 10)

        @kb.add("i")
        def toggle_info(event):
            """Toggle info panel for current item."""
            if self.filter_mode:
                self.filter_text += "i"
                return
            if self.age_filter_mode:
                return
            self.show_info_panel = not self.show_info_panel

        @kb.add("q")
        def quit_app(event):
            if self.selected and not self._quit_warned:
                self.status_message = (
                    "Warning: You have items selected. Press q again to quit."
                )
                self._quit_warned = True
                return  # Don't exit yet
            event.app.exit(result="quit")

        @kb.add("escape")
        def escape_handler(event):
            # Handle age filter mode first
            if self.age_filter_mode:
                self.age_filter_mode = False
                self.age_filter_input = ""
                return
            # Handle filter mode
            if self.filter_mode:
                self.filter_mode = False
                self.filter_text = ""
                return
            # Clear active filter
            if self.filtered_items is not None:
                self._clear_filter()
                self.status_message = "Filter cleared"
                return
            # Close overlays if open, otherwise quit
            if self.show_extensions:
                self.show_extensions = False
            elif self.show_help:
                self.show_help = False
            else:
                if self.selected and not self._quit_warned:
                    self.status_message = (
                        "Warning: You have items selected. Press Esc again to quit."
                    )
                    self._quit_warned = True
                    return  # Don't exit yet
                event.app.exit(result="quit")

        @kb.add("c-c")
        def ctrl_c(event):
            self.cancelled = True
            event.app.exit(result="quit")
            raise KeyboardInterrupt()

        @kb.add("?")
        def toggle_help(event):
            self.show_help = not self.show_help

        @kb.add("<any>")
        def handle_any_key(event):
            """Handle any key - for filter mode input, age filter input, and closing help."""
            if self.show_help:
                self.show_help = False
                return
            if self.age_filter_mode:
                # Only accept digit input for age filter
                key = event.data
                if key and len(key) == 1 and key.isdigit():
                    self.age_filter_input += key
                return
            if self.filter_mode:
                # Add printable characters to filter text
                key = event.data
                if key and len(key) == 1 and key.isprintable():
                    self.filter_text += key

        # Styles
        style = Style.from_dict(
            {
                "path": "bold cyan",
                "path-size": "cyan",
                "title": "bold cyan",
                "help": "dim",
                "help-box": "fg:ansiwhite",
                "hint": "dim italic fg:ansiyellow",
                "header": "bold magenta",
                "normal": "",
                "loading": "dim italic",
                "selected": "green",
                "cursor": "reverse",
                "cursor-selected": "reverse green",
                "selection-summary": "bold bg:ansigreen fg:ansiblack",
                "selection-hint": "dim fg:ansiwhite",
                "footer": "bold",
                "status": "italic fg:ansicyan",
                "dim": "dim",
                "bookmark-hint": "fg:ansigreen",
                # Breadcrumb styles
                "breadcrumb": "fg:ansicyan",
                "breadcrumb-sep": "dim fg:ansiwhite",
                "breadcrumb-dim": "dim",
                "breadcrumb-current": "bold fg:ansicyan",
                # Info panel styles
                "info-header": "bold fg:ansimagenta",
                "info-label": "bold fg:ansiwhite",
                "info-value": "fg:ansicyan",
                "info-dim": "dim",
                # Overlay styles
                "overlay-border": "bold fg:ansicyan",
                "overlay-header": "bold fg:ansimagenta",
                "overlay-row": "fg:ansiwhite",
                "overlay-row-dim": "dim fg:ansiwhite",
                "overlay-total": "bold fg:ansiwhite",
                "overlay-help": "dim italic fg:ansicyan",
                # Filter styles
                "filter-input": "bold fg:ansiyellow",
                "filter-active": "fg:ansiyellow",
            }
        )

        # Create control
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
        self._app = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=True,
            mouse_support=True,
        )

        # Run
        result = self._app.run()

        # Stop any background loading and kill active processes
        self._stop_loading.set()
        self.explorer.kill_active_processes()

        # Clear app reference to break circular reference
        self._app = None

        if result == "delete":
            return self.selected
        return set()

    def _show_selection_view(self) -> None:
        explorer_render.show_selection_view(self)
