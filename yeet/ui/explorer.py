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
from shutil import get_terminal_size

from ..scanner import DiskExplorer
from ..utils import (
    DiskItem,
    SIZE_LOADING,
    format_size,
    format_days_ago,
    open_path,
)


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
                item for item in self.items if pattern in item.name.lower()
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
        """Generate breadcrumb navigation for current path."""
        parts = self.current_path.parts
        if not parts:
            return FormattedText([("class:breadcrumb", "/")])

        # Build breadcrumb parts
        crumbs: list[tuple[str, str]] = []
        separator = " > "

        # Calculate total length to see if we need to abbreviate
        full_path = separator.join(parts)
        if len(full_path) > max_width and len(parts) > 3:
            # Show first, ellipsis, and last 2 parts
            crumbs.append(("class:breadcrumb", parts[0] if parts[0] != "/" else "/"))
            crumbs.append(("class:breadcrumb-sep", separator))
            crumbs.append(("class:breadcrumb-dim", "..."))
            crumbs.append(("class:breadcrumb-sep", separator))
            for i, part in enumerate(parts[-2:]):
                if i > 0:
                    crumbs.append(("class:breadcrumb-sep", separator))
                crumbs.append(("class:breadcrumb", part))
        else:
            # Show full path
            for i, part in enumerate(parts):
                if i > 0:
                    crumbs.append(("class:breadcrumb-sep", separator))
                display = part if part != "/" else "/"
                if i == len(parts) - 1:
                    crumbs.append(("class:breadcrumb-current", display))
                else:
                    crumbs.append(("class:breadcrumb", display))

        return FormattedText(crumbs)

    def _get_parent_total_size(self) -> int | None:
        """Get the total size of items in the current directory."""
        # Sum up all known item sizes
        total = 0
        for item in self.items:
            if item.size > 0 and item.size != SIZE_LOADING:
                total += item.size
        return total if total > 0 else None

    def _get_item_info(self, item: DiskItem) -> FormattedText:
        """Generate detailed info panel for an item."""
        lines: list[tuple[str, str]] = []

        # Full path
        lines.append(("class:info-label", "  Path: "))
        lines.append(("class:info-value", str(item.path)))
        lines.append(("", "\n"))

        # Size
        lines.append(("class:info-label", "  Size: "))
        lines.append(("class:info-value", item.size_formatted))

        # Percentage of parent
        parent_size = self._get_parent_total_size()
        if parent_size and item.size > 0 and item.size != SIZE_LOADING:
            pct = (item.size / parent_size) * 100
            lines.append(("class:info-value", f" ({pct:.1f}% of parent)"))
        lines.append(("", "\n"))

        # Type
        lines.append(("class:info-label", "  Type: "))
        lines.append(("class:info-value", "Directory" if item.is_dir else "File"))
        lines.append(("", "\n"))

        # Item count for directories
        if item.is_dir:
            try:
                count = len(list(item.path.iterdir()))
                lines.append(("class:info-label", "  Items: "))
                lines.append(("class:info-value", str(count)))
                lines.append(("", "\n"))
            except (PermissionError, OSError):
                pass

        # Modified date
        lines.append(("class:info-label", "  Modified: "))
        try:
            lines.append(
                ("class:info-value", item.modified.strftime("%Y-%m-%d %H:%M:%S"))
            )
            lines.append(
                ("class:info-dim", f" ({format_days_ago(item.days_since_modified)})")
            )
        except (OSError, ValueError, AttributeError):
            lines.append(("class:info-value", "Unknown"))
        lines.append(("", "\n"))

        return FormattedText(lines)

    def _get_header(self) -> FormattedText:
        """Generate the table header row."""
        w = self.col_widths
        header = (
            f"{'':>{w['select']}} "
            f"{'':>{w['icon']}}"
            f"{'Name':<{w['name']}} "
            f"{'Size':>{w['size']}} "
            f"{'Modified':>{w['modified']}}"
        )
        return FormattedText([("class:header", header)])

    def _get_row(
        self,
        idx: int,
        display_items: list[DiskItem],
    ) -> FormattedText:
        """Generate a single row for an item."""
        item = display_items[idx]
        w = self.col_widths

        is_selected = item.path in self.selected
        is_cursor = idx == self.cursor

        # Selection indicator
        select_char = "[x]" if is_selected else "[ ]"

        # Directory indicator
        icon = "▸ " if item.is_dir else "  "

        # Truncate name if needed
        name = item.name
        if len(name) > w["name"] - 2:
            name = name[: w["name"] - 5] + "..."

        # Size display
        size_str = item.size_formatted

        # Modified date
        modified = format_days_ago(item.days_since_modified)

        # Build the row
        row = (
            f"{select_char:>{w['select']}} "
            f"{icon}{name:<{w['name']}} "
            f"{size_str:>{w['size']}} "
            f"{modified:>{w['modified']}}"
        )

        # Style based on state
        if is_cursor and is_selected:
            style = "class:cursor-selected"
        elif is_cursor:
            style = "class:cursor"
        elif is_selected:
            style = "class:selected"
        elif item.is_loading:
            style = "class:loading"
        else:
            style = "class:normal"

        return FormattedText([(style, row)])

    def _calculate_extension_stats(self) -> list[tuple[str, int, int]]:
        """
        Calculate file type statistics for the current directory.

        Returns:
            List of tuples: [(extension, count, total_size), ...] sorted by size desc
        """
        stats: dict[str, tuple[int, int]] = {}  # extension -> (count, total_size)

        for item in self.items:
            if item.is_dir:
                ext = "(directories)"
            else:
                # Get extension, lowercase
                suffix = item.path.suffix.lower()
                ext = suffix if suffix else "(no extension)"

            # Use cached size, default to 0 if loading
            size = item.size if item.size > 0 else 0

            if ext in stats:
                count, total = stats[ext]
                stats[ext] = (count + 1, total + size)
            else:
                stats[ext] = (1, size)

        # Convert to list and sort by size descending
        result = [(ext, count, size) for ext, (count, size) in stats.items()]
        result.sort(key=lambda x: x[2], reverse=True)

        return result

    def _get_extensions_content(self) -> FormattedText:
        """Generate content for the file types breakdown overlay."""
        lines: list[tuple[str, str]] = []

        stats = self._calculate_extension_stats()

        # Calculate total size
        total_size = sum(size for _, _, size in stats)
        total_count = sum(count for _, count, _ in stats)

        # Shorten path for display
        path_str = str(self.current_path)
        home = str(Path.home())
        if path_str.startswith(home):
            path_str = "~" + path_str[len(home) :]

        # Truncate if too long
        max_path_len = 40
        if len(path_str) > max_path_len:
            path_str = "..." + path_str[-(max_path_len - 3) :]

        # Box width
        box_width = 60

        # Top border
        title = f" File Types in {path_str} "
        padding = box_width - len(title) - 2
        left_pad = padding // 2
        right_pad = padding - left_pad
        lines.append(("", "\n\n"))
        lines.append(
            ("class:overlay-border", f"  ╭{'─' * left_pad}{title}{'─' * right_pad}╮\n")
        )
        lines.append(("class:overlay-border", f"  │{' ' * (box_width - 2)}│\n"))

        # Header row
        header = "  Extension       Count        Size       % of Total"
        lines.append(("class:overlay-border", "  │"))
        lines.append(("class:overlay-header", f"{header:<{box_width - 4}}"))
        lines.append(("class:overlay-border", "│\n"))

        # Separator
        lines.append(("class:overlay-border", f"  │{'─' * (box_width - 2)}│\n"))

        # Group small extensions into "(other)"
        threshold = total_size * 0.001 if total_size > 0 else 0  # 0.1% threshold
        max_extensions = 15
        other_count = 0
        other_size = 0
        displayed = 0

        for ext, count, size in stats:
            if displayed >= max_extensions or (size < threshold and displayed > 0):
                other_count += count
                other_size += size
            else:
                percent = (size / total_size * 100) if total_size > 0 else 0
                size_str = format_size(size)
                row = f"  {ext:<14} {count:>6}   {size_str:>10}       {percent:>5.1f}%"
                lines.append(("class:overlay-border", "  │"))
                lines.append(("class:overlay-row", f"{row:<{box_width - 4}}"))
                lines.append(("class:overlay-border", "│\n"))
                displayed += 1

        # Add "(other)" row if needed
        if other_count > 0:
            percent = (other_size / total_size * 100) if total_size > 0 else 0
            size_str = format_size(other_size)
            row = f"  {'(other)':<14} {other_count:>6}   {size_str:>10}       {percent:>5.1f}%"
            lines.append(("class:overlay-border", "  │"))
            lines.append(("class:overlay-row-dim", f"{row:<{box_width - 4}}"))
            lines.append(("class:overlay-border", "│\n"))

        # Separator
        lines.append(("class:overlay-border", f"  │{'─' * (box_width - 2)}│\n"))

        # Total row
        total_size_str = format_size(total_size)
        total_row = (
            f"  {'Total':<14} {total_count:>6}   {total_size_str:>10}       100.0%"
        )
        lines.append(("class:overlay-border", "  │"))
        lines.append(("class:overlay-total", f"{total_row:<{box_width - 4}}"))
        lines.append(("class:overlay-border", "│\n"))

        # Empty line
        lines.append(("class:overlay-border", f"  │{' ' * (box_width - 2)}│\n"))

        # Bottom border
        lines.append(("class:overlay-border", f"  ╰{'─' * (box_width - 2)}╯\n"))

        # Instructions
        lines.append(
            ("class:overlay-help", "                   Press 'e' or Esc to close\n")
        )

        return FormattedText(lines)

    def _get_help_content(self) -> FormattedText:
        """Generate the help overlay content."""
        lines: list[tuple[str, str]] = []

        # Build the help box
        help_text = [
            "",
            "╭─────────────────── Keyboard Shortcuts ───────────────────╮",
            "│                                                          │",
            "│  Navigation                                              │",
            "│    ↑/k        Move up                                    │",
            "│    ↓/j        Move down                                  │",
            "│    Enter/l    Open directory                             │",
            "│    h/Backspace Go to parent                              │",
            "│    g          Go to top                                  │",
            "│    G          Go to bottom                               │",
            "│    Ctrl+U     Page up                                    │",
            "│    Ctrl+D     Page down                                  │",
            "│    ~          Go to home directory                       │",
            "│    /          Go to root                                 │",
            "│                                                          │",
            "│  Selection                                               │",
            "│    Space      Toggle selection                           │",
            "│    *          Select all visible                         │",
            "│    u          Deselect all                               │",
            "│                                                          │",
            "│  Filtering                                               │",
            "│    f          Filter by name                             │",
            "│    a          Filter by age (days old)                   │",
            "│    c          Clear name filter                          │",
            "│    A          Clear age filter                           │",
            "│                                                          │",
            "│  Actions                                                 │",
            "│    d          Delete selected                            │",
            "│    v          View selection                             │",
            "│    o          Open in Finder                             │",
            "│    i          Show item info                             │",
            "│    r          Refresh                                    │",
            "│                                                          │",
            "│  Display                                                 │",
            "│    s          Cycle sort mode                            │",
            "│    t          Toggle small items                         │",
            "│    ?          Show/hide this help                        │",
            "│    q/Esc      Quit                                       │",
            "│                                                          │",
            "╰──────────────────────────────────────────────────────────╯",
            "",
            "                    Press any key to close",
            "",
        ]

        for line in help_text:
            lines.append(("class:help-box", f"  {line}\n"))

        return FormattedText(lines)

    def _get_content(self) -> FormattedText:
        """Generate the full screen content."""
        # Show help overlay if active
        if self.show_help:
            return self._get_help_content()

        # Show extensions overlay if active
        if self.show_extensions:
            return self._get_extensions_content()

        lines: list[tuple[str, str]] = []

        # Get items to display (filtered or all)
        display_items = self._get_display_items()

        # Breadcrumb navigation header with size
        cached_size = self.explorer.get_cached_size(self.current_path)
        if cached_size is not None:
            size_str = format_size(cached_size)
        else:
            # Sum up known child sizes as an estimate
            known_size = sum(item.size for item in self.items if item.size > 0)
            if known_size > 0:
                size_str = f"~{format_size(known_size)}"
            else:
                size_str = "..."

        lines.append(("", "\n  "))
        lines.extend(self._get_breadcrumbs())
        lines.append(("class:path-size", f" ({size_str})"))
        lines.append(("", "\n\n"))

        # Instructions with new keybindings
        lines.append(
            (
                "class:help",
                "  [j/k] Navigate  [g/G] Top/Bottom  [Ctrl+U/D] Page  "
                "[Enter] Open  [h] Back  [?] Help\n",
            )
        )
        lines.append(
            (
                "class:help",
                "  [Space] Select  [*] All  [u] None  [d] Delete  [v] View  "
                "[f] Filter  [e] Types  [?] Help  [q] Quit\n",
            )
        )

        # Small items hint
        if not self.show_small_items:
            threshold = format_size(self.explorer.min_size_bytes)
            lines.append(
                (
                    "class:hint",
                    f"  Hiding items < {threshold}. Press [t] to show all.\n",
                )
            )

        lines.append(("", "\n"))

        # Header
        lines.append(("class:header", "  "))
        lines.extend(self._get_header())
        lines.append(("", "\n"))
        lines.append(("class:header", "  " + "─" * 95 + "\n"))

        # Rows
        if not display_items:
            if self.filtered_items is not None:
                lines.append(("class:dim", "  (no items match filter)\n"))
            else:
                lines.append(
                    ("class:dim", "  (empty or no items above size threshold)\n")
                )
        else:
            # Calculate viewport size based on terminal height
            # Reserve lines for: header(~8), footer(~8), info panel if shown(~6)
            term_height = get_terminal_size().lines
            reserved_lines = 16 if not self.show_info_panel else 22
            viewport_size = max(5, term_height - reserved_lines)

            total = len(display_items)
            if total <= viewport_size:
                start, end = 0, total
            else:
                # Window around cursor
                half_viewport = viewport_size // 2
                start = max(0, self.cursor - half_viewport)
                end = min(total, start + viewport_size)
                if end - start < viewport_size:
                    start = max(0, end - viewport_size)

            if start > 0:
                lines.append(("class:dim", f"  ... {start} more items above ...\n"))

            for idx in range(start, end):
                lines.append(("", "  "))
                lines.extend(self._get_row(idx, display_items))
                lines.append(("", "\n"))

            if end < total:
                lines.append(
                    ("class:dim", f"  ... {total - end} more items below ...\n")
                )

        # Footer
        lines.append(("", "\n"))
        lines.append(("class:header", "  " + "─" * 95 + "\n"))

        # Info panel (if enabled)
        if self.show_info_panel and display_items and self.cursor < len(display_items):
            item = display_items[self.cursor]
            lines.append(("class:info-header", "  Item Info:\n"))
            lines.extend(self._get_item_info(item))
            lines.append(("class:header", "  " + "─" * 95 + "\n"))

        # Filter status
        if self.age_filter_mode:
            lines.append(
                (
                    "class:filter-input",
                    f"  Show items older than (days): {self.age_filter_input}_\n",
                )
            )
        elif self.filter_mode:
            lines.append(("class:filter-input", f"  Filter: {self.filter_text}_\n"))
        elif self.filtered_items is not None or self.age_filter_days is not None:
            filter_parts = []
            if self.filter_text:
                filter_parts.append(f'Name: "{self.filter_text}"')
            if self.age_filter_days is not None:
                filter_parts.append(f"Age: >{self.age_filter_days} days")
            filter_str = " | ".join(filter_parts)
            lines.append(
                (
                    "class:filter-active",
                    f"  {filter_str} ({len(self.filtered_items) if self.filtered_items else len(self.items)} of {len(self.items)})  │  [c] Clear name  [A] Clear age\n",
                )
            )

        # Age filter hint
        if (
            self.age_filter_days is not None
            and not self.age_filter_mode
            and not self.filter_mode
        ):
            lines.append(
                (
                    "class:hint",
                    f"  Showing items older than {self.age_filter_days} days | [A] Clear age filter\n",
                )
            )

        # Selection summary - always show prominently at bottom
        total_selected_size = sum(
            self.explorer.get_cached_size(p) or 0 for p in self.selected
        )
        if self.selected:
            lines.append(
                (
                    "class:selection-summary",
                    f"  Selected: {len(self.selected)} items ({format_size(total_selected_size)}) "
                    f"| Press [d] to delete, [v] to view\n",
                )
            )
        else:
            lines.append(
                (
                    "class:selection-hint",
                    "  Selected: 0 items | Press [Space] to select items\n",
                )
            )

        # Status message
        if self.status_message:
            lines.append(("class:status", f"  {self.status_message}\n"))

        # Sort mode indicator
        sort_label = {"size": "Size", "name": "Name", "modified": "Modified"}[
            self.sort_mode
        ]
        lines.append(("class:dim", f"  Sort: {sort_label} | [r] Refresh\n"))

        return FormattedText(lines)

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
                self._show_selection_view(event.app)

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

    def _show_selection_view(self, app: Application) -> None:
        """Show the selection view modal."""
        # This is a simplified version - in a full implementation
        # you'd want a proper modal/overlay
        self.status_message = (
            f"Selection: {len(self.selected)} items - press [d] to delete"
        )
