"""Full-screen pages for the cleanup journey, using the shared terminal chrome."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window, Float, FloatContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from ..formatting import format_size
from ..filesystem import validate_directory
from .application import TerminalApplication
from .chrome import key_hints, screen_title
from .geometry import content_width, fit, single_line
from .theme import THEME
from .view import PageHost, ScreenView, ViewLayout

STYLE = Style.from_dict({**THEME, "danger": "#f87171", "warning": "#fbbf24"})
T = TypeVar("T")


@dataclass(frozen=True)
class ReviewItem:
    path: Path
    size: int
    note: str = ""
    failed: bool = False


class JourneyPage:
    """Scrollable content with independently focused, safe-default actions."""

    def __init__(
        self,
        title: str,
        context: str,
        summary: str,
        items: list[ReviewItem],
        actions: list[tuple[str, str]],
        *,
        note: str = "",
        danger: bool = False,
    ) -> None:
        self.title, self.context, self.summary = title, context, summary
        self.items, self.actions, self.note = items, actions, note
        self.danger = danger
        self.host: PageHost | None = None
        self.cursor = 0
        self.action = 0
        self._view = ViewLayout(self._get_content)

    def within(self, host: PageHost):
        """Present this action in the existing list, retaining its visual context."""
        self.host = host
        return self

    def _row(self, index: int) -> FormattedText:
        if not self.items:
            return FormattedText([("class:detail", "  No matching items.")])
        item = self.items[index]
        width = content_width()
        size = format_size(item.size)
        prefix = "! " if item.failed else "› " if index == self.cursor else "  "
        style = (
            "class:cursor"
            if index == self.cursor
            else "class:warning"
            if item.failed
            else "class:normal"
        )
        return FormattedText(
            [
                (
                    style,
                    "  "
                    + prefix
                    + fit(
                        item.path.name if width < 50 else str(item.path),
                        max(1, width - len(size) - 4),
                    )
                    + "  "
                    + size,
                )
            ]
        )

    def _get_content(self) -> ScreenView:
        if self.host is not None:
            return self._inline_content()
        header = list(screen_title(self.title))
        if self.context:
            header.append(
                (
                    "class:detail",
                    "  " + fit(self.context, content_width()).rstrip() + "\n",
                )
            )
        header.extend(
            [
                ("", "\n"),
                (
                    "class:danger" if self.danger else "class:footer",
                    "  " + fit(self.summary, content_width()).rstrip() + "\n",
                ),
            ]
        )
        if self.note:
            header.append(
                (
                    "class:warning" if self.danger else "class:detail",
                    "  " + fit(self.note, content_width()).rstrip() + "\n",
                )
            )
        header.append(("", "\n"))
        footer = list(self._action_footer())
        if self.items:
            item = self.items[self.cursor]
            footer.append(
                (
                    "class:detail",
                    "  " + fit(str(item.path), content_width()).rstrip() + "\n",
                )
            )
            if item.note:
                footer.append(
                    (
                        "class:warning",
                        "  " + fit(item.note, content_width()).rstrip() + "\n",
                    )
                )
            footer.append(
                ("class:dim", f"  Item {self.cursor + 1}/{len(self.items)}\n")
            )
        return ScreenView(
            FormattedText(header),
            max(1, len(self.items)),
            self._row,
            FormattedText(footer),
            self.cursor,
        )

    def _action_footer(self) -> FormattedText:
        footer = [("", "  ")]
        visible_actions = list(enumerate(self.actions))
        if sum(get_cwidth(label) + 6 for _, label in self.actions) > content_width():
            visible_actions = [(self.action, self.actions[self.action])]
        for index, (_, label) in visible_actions:
            footer.append(
                (
                    "class:cursor" if index == self.action else "class:detail",
                    ("[ " if index == self.action else "  ")
                    + fit(label, max(1, content_width() - 4)).rstrip()
                    + (" ]" if index == self.action else "  "),
                )
            )
            footer.append(("", "  "))
        footer.append(("", "\n"))
        footer.extend(
            key_hints(
                [
                    ("Enter", "choose"),
                    ("Tab/←→", "action"),
                    ("↑↓", "items"),
                    ("Esc", "back"),
                ]
            )
        )
        return FormattedText(footer)

    def _inline_content(self) -> ScreenView:
        assert self.host is not None
        current = self.host.screen_view()
        inline = [
            (
                "class:danger" if self.danger else "class:status",
                "  " + fit(self.summary, content_width()).rstrip() + "\n",
            )
        ]
        focused_path = self.host.focused_path
        item = next((item for item in self.items if item.path == focused_path), None)
        if item is not None:
            if item.note:
                inline.append(
                    (
                        "class:warning" if item.failed else "class:detail",
                        "  " + fit(item.note, content_width()).rstrip() + "\n",
                    )
                )
            inline.append(
                (
                    "class:detail",
                    "  " + fit(str(item.path), content_width()).rstrip() + "\n",
                )
            )
        if self.note:
            inline.append(
                (
                    "class:warning",
                    "  " + fit(self.note, content_width()).rstrip() + "\n",
                )
            )
        # Actions have priority at small heights; the original directory/list
        # remains the body rather than being replaced by another screen.
        return ScreenView(
            current.header,
            current.count,
            current.row,
            FormattedText([*self._action_footer(), *inline]),
            current.cursor,
        )

    def _move(self, delta):
        if self.host is None:
            self.cursor = max(0, min(max(0, len(self.items) - 1), self.cursor + delta))
        else:
            self.host.move(delta)

    def key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def up(event):
            self._move(-1)

        @kb.add("down")
        @kb.add("j")
        def down(event):
            self._move(1)

        @kb.add("pageup")
        def pageup(event):
            self._move(-10)

        @kb.add("pagedown")
        def pagedown(event):
            self._move(10)

        @kb.add("tab")
        @kb.add("right")
        def next_action(event):
            self.action = (self.action + 1) % len(self.actions)

        @kb.add("s-tab")
        @kb.add("left")
        def previous_action(event):
            self.action = (self.action - 1) % len(self.actions)

        @kb.add("enter")
        def choose(event):
            event.app.exit(result=self.actions[self.action][0])

        @kb.add("escape")
        @kb.add("q")
        def back(event):
            event.app.exit(result="back")

        @kb.add("c-c")
        def interrupt(event):
            event.app.exit(exception=KeyboardInterrupt())

        return kb

    def run(self) -> str:
        return TerminalApplication(
            layout=self._view.layout,
            key_bindings=self.key_bindings(),
            style=STYLE,
            color_depth=ColorDepth.TRUE_COLOR,
        ).run()


class ReviewScreen(JourneyPage):
    def __init__(
        self,
        items: list[ReviewItem],
        use_trash: bool,
        context: str = "",
        *,
        trash_unavailable: bool = False,
    ) -> None:
        action = "Move to Trash" if use_trash else "Permanently delete"
        note = (
            "Trash is unavailable. Permanent deletion requires your confirmation."
            if trash_unavailable
            else "Restore items from your system Trash; empty Trash to recover disk space."
            if use_trash
            else "This operation cannot be undone."
        )
        super().__init__(
            "Deletion review",
            context,
            f"{len(items)} items · {format_size(sum(i.size for i in items))} · {action}",
            items,
            [("back", "Back"), ("confirm", action)],
            note=note,
            danger=True,
        )


class ResultsScreen(JourneyPage):
    def __init__(
        self,
        results: list[tuple[ReviewItem, bool, str]],
        use_trash: bool,
        context: str = "",
        *,
        directory: bool = True,
    ) -> None:
        succeeded = sum(ok for _, ok, _ in results)
        size = sum(item.size for item, ok, _ in results if ok)
        label = "Moved to Trash" if use_trash else "Space recovered"
        rows = [
            ReviewItem(
                item.path,
                item.size,
                ("Done · " if ok else "Failed · ") + msg,
                failed=not ok,
            )
            for item, ok, msg in sorted(results, key=lambda result: result[1])
        ]
        actions = [
            ("continue", "Continue in this directory" if directory else "Scan again")
        ]
        if directory:
            actions.append(("directory", "Choose another directory"))
        actions.append(("menu", "Main menu"))
        super().__init__(
            "Cleanup results",
            context,
            f"{succeeded} succeeded · {len(results) - succeeded} failed · {label}: {format_size(size)}",
            rows,
            actions,
            note="Empty Trash to recover disk space."
            if use_trash and succeeded
            else "",
        )


class BusyScreen:
    """Keep blocking scan/removal work off the terminal rendering thread."""

    def __init__(self, title: str, context: str = "") -> None:
        self.title, self.context = title, context
        self.status = "Starting…"
        self.app = None
        self.host: PageHost | None = None

    def within(self, host: PageHost):
        self.host = host
        return self

    def update(self, text: str) -> None:
        self.status = single_line(text)
        if self.app is not None:
            self.app.invalidate()

    def _get_content(self) -> ScreenView:
        if self.host is not None:
            current = self.host.screen_view()
            return ScreenView(
                current.header,
                current.count,
                current.row,
                FormattedText(
                    [
                        (
                            "class:status",
                            "  "
                            + fit(
                                self.title + " · " + self.status, content_width()
                            ).rstrip()
                            + "\n",
                        ),
                        ("class:help", "  Working · please wait\n"),
                    ]
                ),
                current.cursor,
            )

        header = FormattedText(
            [
                *screen_title(self.title),
                (
                    "class:detail",
                    "  " + fit(self.context, content_width()).rstrip() + "\n",
                ),
            ]
        )
        return ScreenView(
            header,
            1,
            lambda _: FormattedText(
                [("class:status", "  " + fit(self.status, content_width()).rstrip())]
            ),
            FormattedText([("class:help", "  Working · please wait\n")]),
        )

    def run(self, work: Callable[[Callable[[str], None]], T]) -> T:
        view = ViewLayout(self._get_content)
        kb = KeyBindings()

        # Never leave a live removal worker running invisibly after Ctrl-C.
        @kb.add("c-c")
        @kb.add("escape")
        def wait(event):
            self.update("Finishing the current operation. Please wait…")

        self.app = TerminalApplication(
            layout=view.layout,
            key_bindings=kb,
            style=STYLE,
            color_depth=ColorDepth.TRUE_COLOR,
        )

        async def execute():
            try:
                result = await asyncio.to_thread(work, self.update)
            except Exception as error:
                self.app.exit(exception=error)
            else:
                self.app.exit(result=result)

        try:
            return self.app.run(
                pre_run=lambda: self.app.create_background_task(execute())
            )
        finally:
            self.app = None


def text_entry(
    title: str,
    context: str,
    initial: str,
    validate: Callable[[str], tuple[bool, object]],
    *,
    completer=None,
    hint: str = "Enter continue · Esc back",
):
    """Editable full-screen input with validation kept in the same page."""
    error = ""

    def accept(buffer):
        nonlocal error
        valid, value = validate(buffer.text.strip())
        if valid:
            app.exit(result=value)
        else:
            error = str(value)
        return True

    field = TextArea(
        text=initial,
        multiline=False,
        completer=completer,
        complete_while_typing=True,
        accept_handler=accept,
        prompt="  › ",
    )
    kb = KeyBindings()

    @kb.add("escape", eager=True)
    def back(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def interrupt(event):
        event.app.exit(exception=KeyboardInterrupt())

    body = HSplit(
        [
            Window(FormattedTextControl(lambda: screen_title(title)), height=2),
            Window(FormattedTextControl(lambda: "  " + single_line(context)), height=2),
            field,
            Window(
                FormattedTextControl(
                    lambda: FormattedText(
                        [("class:warning", "  " + single_line(error))]
                    )
                ),
                height=2,
            ),
            Window(FormattedTextControl("  " + hint), height=1),
        ]
    )
    container = FloatContainer(
        content=body,
        floats=[
            Float(
                xcursor=True,
                ycursor=True,
                content=CompletionsMenu(max_height=8, scroll_offset=1),
            )
        ],
    )
    app = TerminalApplication(
        layout=Layout(container, focused_element=field),
        key_bindings=kb,
        style=STYLE,
        color_depth=ColorDepth.TRUE_COLOR,
    )
    field.buffer.cursor_position = len(initial)
    return app.run()


def choose_directory(initial: Path) -> Path | None:
    from .prompts import PathCompleter

    return text_entry(
        "Choose a directory",
        "Directory to scan · Tab completes paths",
        str(initial),
        validate_directory,
        completer=PathCompleter(),
    )


def confirm_dangerous(paths: list[Path]) -> bool:
    return (
        text_entry(
            "Confirm system paths",
            ", ".join(map(str, paths)),
            "",
            lambda value: (
                value.lower() == "yes",
                True
                if value.lower() == "yes"
                else "Type yes to confirm these system paths.",
            ),
            hint="Type yes · Enter confirm · Esc back",
        )
        is True
    )
