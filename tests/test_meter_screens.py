"""Exercise the live graphics path through the actual app screens."""

import asyncio
from datetime import datetime
from io import StringIO

import pytest
from prompt_toolkit.application import Application, create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output

from yeet.scanner import DiskExplorer
from yeet.ui.explorer import DiskExplorerUI
from yeet.ui.menu import MenuOption, WorkflowMenu
from yeet.ui.selector import (
    CacheSelector,
    DeletionItemSelector,
    InteractiveSelector,
    XcodeSelector,
)
from yeet.utils import (
    CacheCategory,
    CacheLocation,
    LeftoverItem,
    Project,
    ProjectType,
    XcodeItem,
    XcodeItemType,
)


@pytest.mark.parametrize(
    "screen", ["menu", "explorer", "projects", "files", "caches", "xcode"]
)
def test_app_screens_use_the_live_pixel_renderer(screen, tmp_path, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    now = datetime.now()
    path = tmp_path / "item"
    path.write_bytes(b"data" * 256)
    if screen == "menu":
        ui = WorkflowMenu([MenuOption("quit", "Quit", "Exit")], "Workflows")
    elif screen == "explorer":
        ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), tmp_path)
    elif screen == "projects":
        ui = InteractiveSelector(
            [Project(path, "Project", ProjectType.PYTHON, 1024, now, now)]
        )
    elif screen == "files":
        ui = DeletionItemSelector(
            [LeftoverItem(path, "App", "Caches", 1024, now, "App")]
        )
    elif screen == "caches":
        ui = CacheSelector(
            [CacheLocation(path, "Cache", CacheCategory.OTHER, 1024, 1, now)]
        )
    else:
        ui = XcodeSelector(
            [XcodeItem(path, "Build", XcodeItemType.DERIVED_DATA, 1024, now)]
        )

    stream = StringIO()
    output = Vt100_Output(
        stream,
        lambda: Size(rows=30, columns=100),
        default_color_depth=ColorDepth.TRUE_COLOR,
        enable_cpr=False,
    )
    original_run = Application.run

    def run_until_frames(app, *args, **kwargs):
        async def finish_after_frames():
            for _ in range(100):
                if stream.getvalue().count("f=32") >= 3:
                    break
                await asyncio.sleep(0.01)
            app.exit()

        kwargs["pre_run"] = lambda: app.create_background_task(finish_after_frames())
        return original_run(app, *args, **kwargs)

    monkeypatch.setattr(Application, "run", run_until_frames)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
        ui.run()

    rendered = stream.getvalue()
    assert rendered.count("a=T,f=32") == 1
    assert rendered.count("a=f,f=32") >= 2
    assert "a=d,d=I" in rendered
    assert "\x1b[?2026h" in rendered
