"""Interactive menu for workflow selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window, FormattedTextControl
from prompt_toolkit.styles import Style


@dataclass(frozen=True)
class MenuOption:
    """Single selectable menu option."""

    key: str
    label: str
    description: str


class WorkflowMenu:
    """Arrow-navigable menu."""

    def __init__(self, options: list[MenuOption], title: str) -> None:
        self.options = options
        self.title = title
        self.cursor = 0
        self.selected_key: str | None = None
        self.cancelled = False

    def _get_header(self) -> FormattedText:
        return FormattedText(
            [
                ("class:title", f"\n  {self.title}\n\n"),
                ("class:help", "  [↑/↓] Move  [Enter] Select\n\n"),
            ]
        )

    def _get_row(self, idx: int) -> FormattedText:
        option = self.options[idx]
        is_cursor = idx == self.cursor
        row = f"  {'➜' if is_cursor else ' '} {option.label:<18} - {option.description}"
        style = "class:cursor" if is_cursor else "class:normal"
        return FormattedText([(style, row)])

    def _get_content(self) -> FormattedText:
        lines: list[tuple[str, str]] = []
        lines.extend(self._get_header())
        for idx in range(len(self.options)):
            lines.extend(self._get_row(idx))
            lines.append(("", "\n"))
        lines.append(("class:help", "\n  Use arrow keys and Enter.\n"))
        return FormattedText(lines)

    def _move_up(self) -> None:
        self.cursor = (self.cursor - 1) % len(self.options)

    def _move_down(self) -> None:
        self.cursor = (self.cursor + 1) % len(self.options)

    def _choose_current(self) -> None:
        self.selected_key = self.options[self.cursor].key

    def _cancel(self) -> None:
        self.cancelled = True

    def run(self) -> str:
        if not self.options:
            return "quit"

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event) -> None:
            self._move_up()

        @kb.add("down")
        @kb.add("j")
        def _down(event) -> None:
            self._move_down()

        @kb.add("enter")
        def _enter(event) -> None:
            self._choose_current()
            event.app.exit()

        @kb.add("escape")
        def _quit(event) -> None:
            self._cancel()
            event.app.exit()

        style = Style.from_dict(
            {
                "title": "bold cyan",
                "help": "dim",
                "cursor": "bold cyan",
                "normal": "",
            }
        )
        control = FormattedTextControl(text=self._get_content, focusable=True)
        app = Application(
            layout=Layout(HSplit([Window(content=control, wrap_lines=False)])),
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=False,
        )

        app.run()
        return (
            "quit" if self.cancelled or self.selected_key is None else self.selected_key
        )


def build_workflow_menu_options(
    options: Iterable[tuple[str, str, str]],
) -> list[MenuOption]:
    """Build menu options from workflow tuples."""
    menu_options = [
        MenuOption(key=key, label=label, description=description)
        for key, label, description in options
    ]
    menu_options.append(MenuOption(key="quit", label="Quit", description="Exit yeet"))
    return menu_options
