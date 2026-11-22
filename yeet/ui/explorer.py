"""Interactive disk explorer UI with directory traversal."""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import Style

from ..config import get_config
from ..scanners.disk import DiskExplorer
from ..models import SIZE_LOADING, DiskItem
from ..formatting import format_size
from ..filesystem import open_path
from . import explorer_render
from .application import TerminalApplication
from .geometry import terminal_size
from .theme import THEME
from .view import ScreenView, ViewLayout


class DiskExplorerUI:
    def __init__(
        self,
        explorer: DiskExplorer,
        start_path: Path = Path("/"),
    ) -> None:
        self.explorer = explorer
        self._config = get_config()
        self.current_path = start_path
        self.history: deque[Path] = deque(maxlen=100)
        self.items: list[DiskItem] = []
        self.cursor: int = 0
        self.selected: set[Path] = set()
        self.show_small_items: bool = False
        self.sort_mode: str = "size"
        self.status_message: str = ""
        self.cancelled: bool = False

        self._loading_thread: threading.Thread | None = None
        self._stop_loading = threading.Event()
        self._scan_generation = 0
        self.listing = False
        self.pending_entries = 0

        self.filter_mode: bool = False
        self.filter_text: str = ""
        self._name_filter = ""

        self.age_filter_mode: bool = False
        self.age_filter_days: int | None = None
        self.age_filter_input: str = ""

        self.show_extensions: bool = False
        self.overlay_cursor = 0

        self.show_help: bool = False

        self.show_info_panel: bool = False

        self.bookmarks: list[Path] = [
            Path(path).expanduser() for path in self._config.bookmarks
        ]

        self._quit_warned: bool = False

        self._app: Application | None = None
        self._view = ViewLayout(self.screen_view)

    def _scan_current_directory(self) -> None:
        self._stop_loading.set()
        self._scan_generation += 1
        generation = self._scan_generation
        app = self._app
        if app is not None and app.loop is not None:
            stop_event = self._stop_loading = threading.Event()
            path = self.current_path
            loop = app.loop
            self.items = []
            self.listing = True
            self.pending_entries = 0

            def apply_batch(items, pending):
                if generation != self._scan_generation or stop_event.is_set():
                    return
                visible = self._get_display_items()
                focused = (
                    visible[self.cursor].path if self.cursor < len(visible) else None
                )
                self.items = items
                self.listing = pending > 0
                self.pending_entries = pending
                self._sort_items()
                visible = self._get_display_items()
                self.cursor = next(
                    (i for i, item in enumerate(visible) if item.path == focused),
                    min(self.cursor, max(0, len(visible) - 1)),
                )
                if not pending:
                    self._start_lazy_loading()
                app.invalidate()

            def on_update(items, pending):
                if stop_event.is_set():
                    return
                try:
                    loop.call_soon_threadsafe(apply_batch, items, pending)
                except RuntimeError:
                    # The application may have exited while stat was in flight.
                    pass

            def read_directory():
                self.explorer.scan_directory(
                    path, include_small=True, on_update=on_update, stop_event=stop_event
                )

            self._loading_thread = threading.Thread(target=read_directory, daemon=True)
            self._loading_thread.start()
            return

        self.items = self.explorer.scan_directory(
            self.current_path,
            # The meter inventories all children; size filtering belongs to the list.
            include_small=True,
        )
        self._sort_items()

        self._start_lazy_loading()

    def _sort_items(self) -> None:
        if self.sort_mode == "size":
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

    @property
    def filtered_items(self) -> list[DiskItem] | None:
        if not self._name_filter and self.age_filter_days is None:
            return None
        return [
            item
            for item in self.items
            if (
                not self._name_filter
                or self._name_filter in item.name.lower()
                or self._name_filter in str(item.path).lower()
            )
            and (
                self.age_filter_days is None
                or item.days_since_modified >= self.age_filter_days
            )
        ]

    def _apply_filter(self) -> None:
        self._name_filter = self.filter_text.lower()
        self.cursor = 0

    def _clear_filter(self) -> None:
        self.filter_text = self._name_filter = ""
        self.cursor = 0

    def _clear_age_filter(self) -> None:
        self.age_filter_days = None
        self.age_filter_input = ""
        self.cursor = 0

    def _get_display_items(self) -> list[DiskItem]:
        items = self.filtered_items if self.filtered_items is not None else self.items
        if self.show_small_items:
            return items
        return [
            item
            for item in items
            if item.is_loading or item.size >= self.explorer.min_size_bytes
        ]

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

        self._stop_loading.set()
        # Each scan owns its cancellation flag. Reusing and clearing the old
        # event lets stale workers update a new directory; joining blocks keys.
        stop_event = self._stop_loading = threading.Event()

        items_to_load = [
            item for item in self.items if item.is_dir and item.size == SIZE_LOADING
        ]

        if not items_to_load:
            return

        path_to_item = {item.path: item for item in items_to_load}

        term_height = terminal_size().rows
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

        visible_items = [
            item
            for item in self.items[start:end]
            if item.is_dir and item.size == SIZE_LOADING
        ]

        def load_sizes():
            paths = [item.path for item in items_to_load]
            priority_paths = [item.path for item in visible_items]

            def on_size_calculated(path: Path, size: int):
                if stop_event.is_set():
                    return

                def apply_size():
                    if stop_event.is_set():
                        return
                    if path in path_to_item:
                        visible = self._get_display_items()
                        focused = (
                            visible[self.cursor].path
                            if self.cursor < len(visible)
                            else None
                        )
                        path_to_item[path].size = size
                        self._sort_items()

                        visible = self._get_display_items()
                        self.cursor = next(
                            (
                                i
                                for i, item in enumerate(visible)
                                if item.path == focused
                            ),
                            min(self.cursor, max(0, len(visible) - 1)),
                        )
                        if self._app is not None:
                            self._app.invalidate()

                app = self._app
                if app is not None and app.loop is not None:
                    try:
                        app.loop.call_soon_threadsafe(apply_size)
                    except RuntimeError:
                        # The loop may close between completion and dispatch.
                        pass
                else:
                    apply_size()

            self.explorer.calculate_sizes_prioritized(
                paths=paths,
                priority_paths=priority_paths,
                callback=on_size_calculated,
                stop_event=stop_event,
            )

        self._loading_thread = threading.Thread(target=load_sizes, daemon=True)
        self._loading_thread.start()

    @property
    def focused_path(self) -> Path | None:
        items = self._get_display_items()
        return items[self.cursor].path if self.cursor < len(items) else None

    def screen_view(self) -> ScreenView:
        return explorer_render.get_content(self)

    def move(self, delta: int) -> None:
        if self.show_help or self.show_extensions:
            count = explorer_render.overlay_length(self)
            self.overlay_cursor = max(
                0, min(max(0, count - 1), self.overlay_cursor + delta)
            )
        else:
            self.cursor = max(
                0, min(max(0, len(self._get_display_items()) - 1), self.cursor + delta)
            )

    def navigate_into(self, item: DiskItem) -> None:
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
        if path.is_dir():
            self.history.append(self.current_path)
            self.current_path = path
            self.cursor = 0
            self._clear_filter()
            self._scan_current_directory()
            self.status_message = ""

    def toggle_selection(self) -> None:
        display_items = self._get_display_items()
        if not display_items or self.cursor >= len(display_items):
            return

        item = display_items[self.cursor]
        if item.path in self.selected:
            self.selected.discard(item.path)
        else:
            self.selected.add(item.path)

    def cycle_sort_mode(self) -> None:
        modes = ["size", "name", "modified"]
        current_idx = modes.index(self.sort_mode)
        self.sort_mode = modes[(current_idx + 1) % len(modes)]
        self._sort_items()
        self.status_message = f"Sort by: {self.sort_mode}"

    def toggle_small_items(self) -> None:
        self.show_small_items = not self.show_small_items
        self._scan_current_directory()
        if self.show_small_items:
            self.status_message = "Showing all items"
        else:
            self.status_message = (
                f"Hiding items < {format_size(self.explorer.min_size_bytes)}"
            )

    def refresh(self) -> None:
        self._scan_current_directory()
        self.status_message = "Refreshed"

    def key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        commands = Condition(lambda: not (self.filter_mode or self.age_filter_mode))

        @kb.add("up", filter=commands)
        @kb.add("k", filter=commands)
        def move_up(event):
            self.move(-1)

        @kb.add("down", filter=commands)
        @kb.add("j", filter=commands)
        def move_down(event):
            self.move(1)

        @kb.add("enter")
        def open_dir_or_apply_filter(event):
            if self.age_filter_mode:
                if self.age_filter_input:
                    try:
                        self.age_filter_days = int(self.age_filter_input)
                        self.cursor = 0
                        self.status_message = (
                            f"Showing items older than {self.age_filter_days} days"
                        )
                    except ValueError:
                        self.status_message = "Invalid number"
                self.age_filter_mode = False
                self.age_filter_input = ""
                return
            if self.filter_mode:
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

        @kb.add("l", filter=commands)
        def open_dir(event):
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
                self.age_filter_input = self.age_filter_input[:-1]
                return
            if self.filter_mode:
                self.filter_text = self.filter_text[:-1]
                return
            self.navigate_back()

        @kb.add("h", filter=commands)
        def go_back(event):
            self.navigate_back()

        @kb.add("space", filter=commands)
        def toggle_select(event):
            self.toggle_selection()

        @kb.add("*", filter=commands)
        def select_all_visible(event):
            display_items = self._get_display_items()
            for item in display_items:
                self.selected.add(item.path)
            self.status_message = f"Selected {len(display_items)} items"

        @kb.add("u", filter=commands)
        def deselect_all(event):
            count = len(self.selected)
            self.selected.clear()
            self.status_message = f"Deselected {count} items"

        @kb.add("s", filter=commands)
        def cycle_sort(event):
            self.cycle_sort_mode()

        @kb.add("t", filter=commands)
        def toggle_small(event):
            self.toggle_small_items()

        @kb.add("r", filter=commands)
        def refresh_dir(event):
            self.refresh()

        @kb.add("b", filter=commands)
        def go_next_bookmark(event):
            self._go_to_next_bookmark()

        @kb.add("B", filter=commands)
        def bookmark_current(event):
            self._bookmark_current_path()

        @kb.add("o", filter=commands)
        def open_in_finder(event):
            display_items = self._get_display_items()
            if display_items and self.cursor < len(display_items):
                item = display_items[self.cursor]
                _success, msg = open_path(item.path)
                self.status_message = msg

        @kb.add("~", filter=commands)
        def go_home(event):
            self.navigate_to(Path.home())

        @kb.add("/", filter=commands)
        def go_root(event):
            self.navigate_to(Path("/"))

        @kb.add("v", filter=commands)
        def view_selection(event):
            if self.selected:
                self.status_message = (
                    f"Selection: {len(self.selected)} items - press [d] to delete"
                )

        @kb.add("d", filter=commands)
        def delete_selected(event):
            if self.selected:
                event.app.exit(result="delete")

        @kb.add("e", filter=commands)
        def toggle_extensions(event):
            self.overlay_cursor = 0
            self.show_extensions = not self.show_extensions

        @kb.add("f", filter=commands)
        def start_filter(event):
            self.filter_mode = True
            self.filter_text = ""

        @kb.add("c", filter=commands)
        def clear_filter(event):
            if self.filtered_items is not None or self.filter_text:
                self._clear_filter()
                self.status_message = "Name filter cleared"

        @kb.add("a", filter=commands)
        def start_age_filter(event):
            self.age_filter_mode = True
            self.age_filter_input = ""

        @kb.add("A", filter=commands)
        def clear_age_filter(event):
            if self.age_filter_days is not None:
                self._clear_age_filter()
                self.status_message = "Age filter cleared"

        @kb.add("g", filter=commands)
        def go_to_top(event):
            self.move(-max(len(self.items), explorer_render.overlay_length(self)))

        @kb.add("G", filter=commands)
        def go_to_bottom(event):
            self.move(max(len(self.items), explorer_render.overlay_length(self)))

        @kb.add("c-u", filter=commands)
        @kb.add("pageup", filter=commands)
        def page_up(event):
            self.move(-10)

        @kb.add("c-d", filter=commands)
        @kb.add("pagedown", filter=commands)
        def page_down(event):
            self.move(10)

        @kb.add("i", filter=commands)
        def toggle_info(event):
            self.show_info_panel = not self.show_info_panel

        @kb.add("q", filter=commands)
        def quit_app(event):
            if self.selected and not self._quit_warned:
                self.status_message = (
                    "Warning: You have items selected. Press q again to quit."
                )
                self._quit_warned = True
                return
            event.app.exit(result="quit")

        @kb.add("escape")
        def escape_handler(event):

            if self.age_filter_mode:
                self.age_filter_mode = False
                self.age_filter_input = ""
                return

            if self.filter_mode:
                self.filter_mode = False
                self.filter_text = ""
                return

            if self.filtered_items is not None:
                self._clear_filter()
                self.status_message = "Filter cleared"
                return

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
                    return
                event.app.exit(result="quit")

        @kb.add("c-c")
        def ctrl_c(event):
            self.cancelled = True
            event.app.exit(result="quit")
            raise KeyboardInterrupt()

        @kb.add("?", filter=commands)
        def toggle_help(event):
            self.overlay_cursor = 0
            self.show_help = not self.show_help

        @kb.add("<any>")
        def handle_any_key(event):
            if self.show_help:
                self.show_help = False
                return
            if self.age_filter_mode:
                key = event.data
                if key and len(key) == 1 and key.isdigit():
                    self.age_filter_input += key
                return
            if self.filter_mode:
                key = event.data
                if key and len(key) == 1 and key.isprintable():
                    self.filter_text += key

        return kb

    def run(self, *, refresh: bool = True) -> set[Path]:

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
                "breadcrumb": "fg:ansicyan",
                "breadcrumb-sep": "dim fg:ansiwhite",
                "breadcrumb-dim": "dim",
                "breadcrumb-current": "bold fg:ansicyan",
                "info-header": "bold fg:ansimagenta",
                "info-label": "bold fg:ansiwhite",
                "info-value": "fg:ansicyan",
                "info-dim": "dim",
                "overlay-border": "bold fg:ansicyan",
                "overlay-header": "bold fg:ansimagenta",
                "overlay-row": "fg:ansiwhite",
                "overlay-row-dim": "dim fg:ansiwhite",
                "overlay-total": "bold fg:ansiwhite",
                "overlay-help": "dim italic fg:ansicyan",
                "filter-input": "bold fg:ansiyellow",
                "filter-active": "fg:ansiyellow",
                **THEME,
            }
        )

        view = self._view
        self._app = TerminalApplication(
            layout=view.layout,
            key_bindings=self.key_bindings(),
            color_depth=ColorDepth.TRUE_COLOR,
            style=style,
            full_screen=True,
            mouse_support=True,
        )
        if not refresh:
            self._app.pre_run_callables.append(
                lambda: setattr(
                    view.body, "vertical_scroll", getattr(self, "_scroll", 0)
                )
            )
        self.cancelled = False
        self._quit_warned = False
        self._app.pre_run_callables.append(
            self._scan_current_directory
            if refresh or self.listing
            else self._start_lazy_loading
        )

        try:
            result = self._app.run()
        finally:
            # Also discard callbacks queued just before an exceptional exit.
            self._scroll = view.body.vertical_scroll
            self._stop_loading.set()
            self._scan_generation += 1
            self.explorer.kill_active_processes()
            self._app = None

        if result == "delete":
            return self.selected
        return set()
