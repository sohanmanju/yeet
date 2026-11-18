"""One run's terminal synchronization, geometry watcher and pixel worker."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from itertools import count
from time import monotonic
from typing import final

from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Size
from prompt_toolkit.formatted_text import FormattedText

from .geometry import cell_size
from .meter_canvas import BarModel
from .meter_pixels import (
    PLACEHOLDER,
    ROW_MARKS,
    CanvasWorker,
    SurfaceGeometry,
    SurfaceRequest,
)

_IDS = count(0x590000)


@final
class TerminalSession:
    """Own every task and surface for exactly one Application.run_async call."""

    def __init__(self, app: Application) -> None:
        self.app = app
        self.running = False
        self.image_id = 0
        self.request: SurfaceRequest | None = None
        self.presented_geometry: SurfaceGeometry | None = None
        self.visible = False
        self.requested_in_render = False
        self.sync_depth = 0
        self.executor: ThreadPoolExecutor | None = None
        self.tasks: list[asyncio.Task] = []
        self.changed: asyncio.Event | None = None

    async def __aenter__(self) -> TerminalSession:
        self.running = True
        self.image_id = next(_IDS)
        self.request = None
        self.presented_geometry = None
        self.visible = self.requested_in_render = False
        self.changed = asyncio.Event()
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="yeet-pixels"
        )
        self.tasks = [
            asyncio.create_task(
                self.watch_geometry(
                    (self.app.output.get_size(), cell_size(self.app.output))
                )
            ),
            asyncio.create_task(self.animate(CanvasWorker())),
        ]
        for task in self.tasks:
            task.add_done_callback(self.task_finished)
        return self

    def task_finished(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            error = task.exception()
            if (
                error is not None
                and self.running
                and self.app.is_running
                and not self.app.is_done
            ):
                self.app.exit(exception=error)

    async def __aexit__(self, *exc) -> None:
        self.running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        if self.executor is not None:
            await asyncio.to_thread(
                self.executor.shutdown, wait=True, cancel_futures=True
            )
            self.executor = None
        if self.presented_geometry is not None:
            with self.synchronized():
                self.app.output.write_raw(f"\x1b_Ga=d,d=I,i={self.image_id},q=2\x1b\\")
        self.request = None
        self.presented_geometry = None
        self.changed = None
        self.visible = self.requested_in_render = False
        while self.sync_depth:
            self.end_update()

    def begin_update(self) -> None:
        if not self.sync_depth:
            self.app.output.write_raw("\x1b[?2026h")
        self.sync_depth += 1

    def end_update(self) -> None:
        assert self.sync_depth > 0, "unbalanced terminal update"
        self.sync_depth -= 1
        if not self.sync_depth:
            self.app.output.write_raw("\x1b[?2026l")
            self.app.output.flush()

    @contextmanager
    def synchronized(self) -> Iterator[None]:
        self.begin_update()
        try:
            yield
        finally:
            self.end_update()

    def begin_render(self) -> None:
        self.begin_update()
        self.requested_in_render = False

    def end_render(self) -> None:
        visible = self.requested_in_render and not self.app.is_done
        if visible != self.visible and self.changed is not None:
            self.changed.set()
        self.visible = visible
        self.end_update()

    def meter(
        self, model: BarModel, columns: int, context: str | None
    ) -> FormattedText:
        cw, ch = cell_size(self.app.output)
        geometry = SurfaceGeometry.for_terminal(
            columns, self.app.output.get_size().rows, cw, ch
        )
        request = SurfaceRequest(model, geometry, context)
        if request != self.request:
            self.request = request
            if self.changed is not None:
                self.changed.set()
        self.requested_in_render = True
        style = f"fg:#{self.image_id:06x}"
        fragments = []
        for row in range(geometry.rows):
            fragments.extend(
                [
                    ("", "  "),
                    (style, PLACEHOLDER + ROW_MARKS[row] + PLACEHOLDER * (columns - 1)),
                    ("", "\n"),
                ]
            )
        return FormattedText(fragments)

    async def watch_geometry(self, previous: tuple[Size, tuple[int, int]]) -> None:
        while True:
            await asyncio.sleep(0.1)
            current = self.app.output.get_size(), cell_size(self.app.output)
            if current != previous:
                previous = current
                self.app.invalidate()

    async def animate(self, worker: CanvasWorker) -> None:
        # Only one computation may be in flight. Changes replace the pending
        # immutable request rather than queueing frames behind slow rendering.
        assert self.changed is not None and self.executor is not None
        loop = asyncio.get_running_loop()
        last = monotonic() - 0.016
        while True:
            self.changed.clear()
            request = self.request
            if not self.visible or request is None:
                await self.changed.wait()
                last = monotonic() - 0.016
                continue
            started = monotonic()
            frame = await loop.run_in_executor(
                self.executor,
                worker.render,
                request,
                started - last,
                self.image_id,
                request.geometry == self.presented_geometry,
            )
            last = started
            if self.running and self.visible and request == self.request:
                with self.synchronized():
                    self.app.output.write_raw(frame.commands)
                self.presented_geometry = request.geometry
            elapsed = monotonic() - started
            # Keep idle animation from consuming a core on large/HiDPI terminals.
            interval = max(
                0.016 if frame.moving else 0.096, elapsed * (2 if frame.moving else 4)
            )
            try:
                await asyncio.wait_for(
                    self.changed.wait(), max(0.001, interval - elapsed)
                )
            except asyncio.TimeoutError:
                pass
