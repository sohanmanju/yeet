"""Native header/body/footer windows with lazy, cursor-aware row rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import FormattedText, fragment_list_to_text
from prompt_toolkit.layout import HSplit, Layout, ScrollOffsets, Window
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.dimension import Dimension

from .geometry import single_line, terminal_size


@dataclass(frozen=True)
class ScreenView:
    header: FormattedText
    count: int
    row: Callable[[int], FormattedText]
    footer: FormattedText
    cursor: int = 0


class RowControl(UIControl):
    def __init__(self, view: Callable[[], ScreenView]) -> None:
        self.view = view

    def is_focusable(self) -> bool:
        return True

    def create_content(self, width: int, height: int) -> UIContent:
        view = self.view()

        def line(index: int) -> FormattedText:
            if not view.count:
                return FormattedText([])
            return FormattedText(
                [(style, single_line(text)) for style, text in view.row(index)]
            )

        return UIContent(
            get_line=line,
            line_count=max(1, view.count),
            cursor_position=Point(0, min(view.cursor, max(0, view.count - 1))),
        )


class ViewLayout:
    """Let Prompt Toolkit allocate window heights, clip cells and scroll rows."""

    def __init__(self, provider: Callable[[], ScreenView]) -> None:
        self.provider = provider
        self.cached_view: ScreenView | None = None
        self.cache_key: tuple[object, int] | None = None
        self.body = Window(
            RowControl(self.current),
            wrap_lines=False,
            always_hide_cursor=True,
            height=Dimension(min=1, weight=1),
            scroll_offsets=ScrollOffsets(top=1, bottom=1),
        )
        header = Window(
            FormattedTextControl(lambda: self.current().header),
            wrap_lines=False,
            always_hide_cursor=True,
            height=lambda: self.chrome_height(True),
            dont_extend_height=True,
        )
        footer = Window(
            FormattedTextControl(lambda: self.current().footer),
            wrap_lines=False,
            always_hide_cursor=True,
            height=lambda: self.chrome_height(False),
            dont_extend_height=True,
        )
        self.layout = Layout(
            HSplit([header, self.body, footer]), focused_element=self.body
        )

    def current(self) -> ScreenView:
        app = get_app_or_none()
        key = (app, app.render_counter) if app is not None and app.is_running else None
        if key is None or key != self.cache_key or self.cached_view is None:
            self.cached_view = self.provider()
            self.cache_key = key
        return self.cached_view

    def chrome_height(self, header: bool) -> Dimension:
        view = self.current()
        height = max(1, terminal_size().rows)
        footer_rows = min(self.line_count(view.footer), max(1, height // 3))
        if header:
            preferred = self.line_count(view.header)
            maximum = max(0, height - footer_rows - 1)
        else:
            preferred = footer_rows
            maximum = footer_rows
        return Dimension(min=0, max=maximum, preferred=min(preferred, maximum))

    @staticmethod
    def line_count(text: FormattedText) -> int:
        return len(fragment_list_to_text(text).splitlines())
