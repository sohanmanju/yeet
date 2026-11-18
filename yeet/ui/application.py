"""Application with an explicit, reusable rendering-session lifetime."""

from __future__ import annotations

from prompt_toolkit import Application

from .render_session import TerminalSession


class TerminalApplication(Application):
    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("full_screen", True)
        kwargs.setdefault("terminal_size_polling_interval", None)
        kwargs.setdefault("min_redraw_interval", 0.016)
        super().__init__(**kwargs)
        self.session = TerminalSession(self)
        self.before_render += self._begin_render
        self.after_render += self._end_render

    def _begin_render(self, app: Application) -> None:
        self.session.begin_render()

    def _end_render(self, app: Application) -> None:
        self.session.end_render()

    async def run_async(self, *args, **kwargs):
        async with self.session:
            return await super().run_async(*args, **kwargs)

    def _on_resize(self) -> None:
        # Include Prompt Toolkit's pre-render erase in the same atomic update.
        with self.session.synchronized():
            super()._on_resize()
