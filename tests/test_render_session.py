"""Session reuse, worker isolation, superseded frames and exceptional teardown."""

import asyncio
import re
import threading
from datetime import datetime
from io import StringIO

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout import FormattedTextControl, Layout, Window
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output

from yeet.ui.application import TerminalApplication
from yeet.ui.meter import Segment, dot_meter
from yeet.ui.meter_pixels import CanvasWorker
from yeet.ui.selector import DeletionItemSelector
from yeet.ui.view import ScreenView, ViewLayout
from yeet.utils import LargeFile


@pytest.fixture(autouse=True)
def graphics_terminal(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)


def output_for(stream):
    return Vt100_Output(
        stream,
        lambda: Size(rows=24, columns=80),
        default_color_depth=ColorDepth.TRUE_COLOR,
        enable_cpr=False,
    )


async def until(predicate):
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("Timed out waiting for the application")


def test_application_reuse_creates_and_releases_a_new_surface_each_run():
    async def scenario():
        stream = StringIO()
        output = output_for(stream)
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
            view = ViewLayout(
                lambda: ScreenView(
                    dot_meter([Segment("Apps", 50, "#3b82f6")], 100),
                    1,
                    lambda _: FormattedText([("", "row")]),
                    FormattedText([]),
                )
            )
            app = TerminalApplication(
                layout=view.layout,
                input=pipe,
                output=output,
                color_depth=ColorDepth.TRUE_COLOR,
            )
            ids = []
            for _ in range(2):
                offset = len(stream.getvalue())
                task = asyncio.create_task(app.run_async())
                try:
                    await until(
                        lambda offset=offset: (
                            stream.getvalue()[offset:].count("a=f,f=32") >= 2
                        )
                    )
                finally:
                    app.exit()
                    await task
                chunk = stream.getvalue()[offset:]
                assert chunk.count("a=T,f=32") == 1
                assert chunk.count("a=d,d=I") == 1
                ids.append(re.search(r"a=T,f=32,[^;]*?i=(\d+)", chunk).group(1))
                assert app.session.request is None
                assert app.session.presented_geometry is None
                assert app.session.tasks == [] and app.session.executor is None
                assert app.session.sync_depth == 0
            assert ids[0] != ids[1]

    asyncio.run(scenario())


def test_slow_rasterizer_does_not_block_keys_or_queue_outdated_frames(
    tmp_path, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    threads = []
    original_render = CanvasWorker.render

    def slow_render(worker, *args):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return original_render(worker, *args)

    monkeypatch.setattr(CanvasWorker, "render", slow_render)

    async def scenario():
        now = datetime.now()
        files = [
            LargeFile(tmp_path / name, name, 100, now, now)
            for name in ("one.zip", "two.mov")
        ]
        ui = DeletionItemSelector(files)
        view = ViewLayout(ui._get_content)
        stream = StringIO()
        output = output_for(stream)
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
            app = TerminalApplication(
                layout=view.layout,
                key_bindings=ui.key_bindings(),
                input=pipe,
                output=output,
                color_depth=ColorDepth.TRUE_COLOR,
            )
            task = asyncio.create_task(app.run_async())
            try:
                await until(started.is_set)
                pipe.send_text("j ")
                await until(lambda: ui.cursor == 1 and ui.selected == {1})
                await until(lambda: app.session.request.model.hover == "1")
                assert (
                    len(threads) == 1
                )  # One in-flight job; key updates have not queued more.
                assert threads[0] != threading.get_ident()
                assert "a=T,f=32" not in stream.getvalue()
                release.set()
                await until(lambda: app.session.presented_geometry is not None)
            finally:
                release.set()
                app.exit()
                await task
        assert stream.getvalue().count("a=T,f=32") == 1

    asyncio.run(scenario())


def test_worker_failure_exits_the_application_and_cleans_up(monkeypatch):
    def fail(*args):
        raise RuntimeError("rasterizer failed")

    monkeypatch.setattr(CanvasWorker, "render", fail)

    async def scenario():
        stream = StringIO()
        output = output_for(stream)
        with create_pipe_input() as pipe:
            app = TerminalApplication(
                layout=Layout(
                    Window(
                        FormattedTextControl(
                            lambda: dot_meter([Segment("Apps", 50, "#3b82f6")], 100)
                        )
                    )
                ),
                input=pipe,
                output=output,
                color_depth=ColorDepth.TRUE_COLOR,
            )
            with pytest.raises(RuntimeError, match="rasterizer failed"):
                await asyncio.wait_for(app.run_async(), 2)
            assert app.session.tasks == [] and app.session.executor is None
            assert app.session.sync_depth == 0

    asyncio.run(scenario())
