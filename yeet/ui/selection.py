"""One typed navigation/selection engine for all cleanup workflows."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Generic

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import Style

from ..utils import format_size
from .application import TerminalApplication
from .geometry import content_width, single_line
from .meter import THEME, ScanBreakdown
from .responsive import TableSchema, table_line
from .selection_model import SectionRow, SelectionRow, T
from .view import ScreenView, ViewLayout


class SelectionEngine(Generic[T]):
    def __init__(
        self,
        rows: Sequence[SelectionRow[T]],
        schema: TableSchema,
        title: str,
        noun: str,
        *,
        open_item: Callable[[T], tuple[bool, str]] | None = None,
        extra_help: str = "",
    ) -> None:
        self.rows = tuple(rows)
        self.schema, self.title, self.noun = schema, title, noun
        self.open_item = open_item
        self.extra_help = extra_help
        self.cursor = 0
        self.selected: set[int] = set()
        self.cancelled = False
        self.status_message = ""
        self.meter = ScanBreakdown([(row.group, row.size) for row in self.rows])
        self.display_rows: list[SectionRow | SelectionRow[T]] = []
        self.positions: list[int] = []
        previous_section = ""
        for row in self.rows:
            if row.section and row.section != previous_section:
                self.display_rows.append(SectionRow(row.section))
            self.positions.append(len(self.display_rows))
            self.display_rows.append(row)
            previous_section = row.section

    def move(self, delta: int) -> None:
        self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))

    def toggle(self) -> None:
        if self.rows:
            index = self.rows[self.cursor].index
            if index in self.selected:
                self.selected.remove(index)
            else:
                self.selected.add(index)

    def select_all(self) -> None:
        self.selected = {row.index for row in self.rows if row.bulk_selectable}

    def _get_header(self) -> FormattedText:
        return FormattedText([("class:header", "  " + table_line(self.schema))])

    def _get_row(self, index: int) -> FormattedText:
        return self.render_item(self.rows[index])

    def render_item(self, row: SelectionRow[T]) -> FormattedText:
        selected = row.index in self.selected
        focused = bool(self.rows) and row.index == self.rows[self.cursor].index
        if row.tone:
            style = row.focus_tone if focused else row.tone
        elif focused:
            style = "class:cursor-selected" if selected else "class:cursor"
        else:
            style = "class:selected" if selected else "class:normal"
        values = {
            **row.cells,
            "select": "[x]" if selected else "[ ]",
            "num": str(row.index + 1),
        }
        return FormattedText(
            [
                (f"fg:{self.meter.color_for(row.group)}", "● "),
                (style, table_line(self.schema, values)),
            ]
        )

    def display_row(self, position: int) -> FormattedText:
        row = self.display_rows[position]
        if isinstance(row, SectionRow):
            return FormattedText(
                [("class:section-header", f"  ── {single_line(row.title)} ──")]
            )
        return FormattedText([("", "  "), *self.render_item(row)])

    def _get_content(self) -> ScreenView:
        focused = self.rows[self.cursor] if self.rows else None
        header = [("class:title", f"  {single_line(self.title)}\n")]
        header.extend(self.meter.render(focused.group if focused else None))
        header.extend(
            [
                ("", "  "),
                *self._get_header(),
                ("", "\n"),
                ("class:header", "  " + "─" * content_width() + "\n"),
            ]
        )
        size = sum(row.size for row in self.rows if row.index in self.selected)
        footer = [
            (
                "class:footer",
                f"  Selected: {len(self.selected)} {self.noun} ({format_size(size)})\n",
            )
        ]
        hints = (
            "q back · Enter OK · Space select"
            if content_width() < 65
            else "j/k move · Space select · Enter confirm · a all · n none · q cancel"
        )
        footer.append(("class:help", "  " + hints + "\n"))
        footer.append(
            (
                "class:dim",
                f"  Rows {self.cursor + 1 if self.rows else 0}/{len(self.rows)}\n",
            )
        )
        if self.status_message:
            footer.append(
                ("class:status", "  " + single_line(self.status_message) + "\n")
            )
        if self.extra_help:
            footer.append(("class:help-extra", "  " + self.extra_help + "\n"))
        position = self.positions[self.cursor] if self.positions else 0
        return ScreenView(
            FormattedText(header),
            len(self.display_rows),
            self.display_row,
            FormattedText(footer),
            position,
        )

    def key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def up(event):
            self.move(-1)

        @kb.add("down")
        @kb.add("j")
        def down(event):
            self.move(1)

        @kb.add("pageup")
        def page_up(event):
            self.move(-10)

        @kb.add("pagedown")
        def page_down(event):
            self.move(10)

        @kb.add("space")
        def toggle(event):
            self.toggle()

        @kb.add("a")
        def all_items(event):
            self.select_all()

        @kb.add("n")
        def none(event):
            self.selected.clear()

        @kb.add("enter")
        def confirm(event):
            event.app.exit()

        @kb.add("escape")
        @kb.add("q")
        def cancel(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit()

        @kb.add("c-c")
        def interrupt(event):
            self.cancelled = True
            self.selected.clear()
            event.app.exit(exception=KeyboardInterrupt())

        if self.open_item is not None:

            @kb.add("o")
            def open_current(event):
                if self.rows:
                    row = self.rows[self.cursor]
                    assert self.open_item is not None
                    success, message = self.open_item(row.value)
                    self.status_message = (
                        f"Opened: {row.name}" if success else f"Error: {message}"
                    )

        return kb

    def run(self) -> list[T]:
        if not self.rows:
            return []
        self.cancelled = False
        view = ViewLayout(self._get_content)
        app = TerminalApplication(
            layout=view.layout,
            key_bindings=self.key_bindings(),
            style=Style.from_dict(
                {
                    **THEME,
                    "section-header": "bold yellow",
                    "latest": "dim cyan",
                    "cursor-latest": "reverse cyan",
                }
            ),
            color_depth=ColorDepth.TRUE_COLOR,
            mouse_support=True,
        )
        app.run()
        if self.cancelled:
            return []
        return [
            row.value
            for row in sorted(self.rows, key=lambda row: row.index)
            if row.index in self.selected
        ]
