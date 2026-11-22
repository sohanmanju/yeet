"""Interactive menu for workflow selection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from .application import TerminalApplication
from .chrome import key_hints
from .geometry import content_width, fit
from .meter import disk_overview
from .theme import THEME
from .view import ScreenView, ViewLayout


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
        return FormattedText([("class:brand", "  yeet\n\n")])

    def _get_row(self, idx: int) -> FormattedText:
        option = self.options[idx]
        width = content_width()
        focused = idx == self.cursor
        style = "class:cursor" if focused else "class:normal"
        prefix = f"  {'›' if focused else ' '} "
        label_width = min(24, max(get_cwidth(item.label) for item in self.options))
        description_width = width - 2 - label_width - 3
        if description_width < 20:
            return FormattedText([(style, prefix + fit(option.label, width - 2))])
        return FormattedText(
            [
                (style, prefix + fit(option.label, label_width) + "   "),
                (
                    "class:menu-description-focus"
                    if focused
                    else "class:menu-description",
                    fit(option.description, description_width),
                ),
            ]
        )

    def _get_content(self) -> ScreenView:
        header = list(self._get_header())
        header.extend(disk_overview(Path.home()))
        header.append(("", "\n"))
        footer = key_hints([("Enter", "open"), ("↑↓", "move"), ("q", "quit")])
        return ScreenView(
            FormattedText(header),
            len(self.options),
            self._get_row,
            FormattedText(footer),
            self.cursor,
        )

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

        @kb.add("q")
        @kb.add("escape")
        def _quit(event) -> None:
            self._cancel()
            event.app.exit()

        style = Style.from_dict(
            {
                **THEME,
            }
        )
        view = ViewLayout(self._get_content)
        app = TerminalApplication(
            layout=view.layout,
            key_bindings=kb,
            color_depth=ColorDepth.TRUE_COLOR,
            style=style,
            full_screen=True,
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
