"""Responsive layouts and live SIGWINCH/polling redraw behavior."""

import asyncio
from datetime import datetime
from io import StringIO

import pytest
from prompt_toolkit.application import Application, create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.utils import get_cwidth

import yeet.ui.meter as meters
import yeet.ui.render_session as sessions
from yeet.scanner import DiskExplorer
from yeet.ui import responsive
from yeet.ui.application import TerminalApplication
from yeet.ui.explorer import DiskExplorerUI
from yeet.ui.menu import MenuOption, WorkflowMenu
from yeet.ui.selector import (
    CacheSelector,
    DeletionItemSelector,
    InteractiveSelector,
    XcodeSelector,
)
from yeet.ui.table_schemas import FILES
from yeet.ui.view import ViewLayout
from yeet.utils import (
    CacheCategory,
    CacheLocation,
    DiskItem,
    LargeFile,
    Project,
    ProjectType,
    XcodeItem,
    XcodeItemType,
)


def make_screen(kind, root):
    now = datetime.now()
    names = [f"{i:03}-漢字-long-item-name" for i in range(40)]
    if kind == "menu":
        ui = WorkflowMenu(
            [MenuOption(str(i), name, "Description") for i, name in enumerate(names)],
            "Workflows",
        )
    elif kind == "files":
        ui = DeletionItemSelector(
            [LargeFile(root / (name + ".zip"), name, 1024, now, now) for name in names]
        )
    elif kind == "projects":
        ui = InteractiveSelector(
            [
                Project(root / name, name, ProjectType.PYTHON, 1024, now, now)
                for name in names
            ]
        )
    elif kind == "caches":
        ui = CacheSelector(
            [
                CacheLocation(root / name, name, CacheCategory.OTHER, 1024, 1, now)
                for name in names
            ]
        )
    elif kind == "xcode":
        ui = XcodeSelector(
            [
                XcodeItem(root / name, name, XcodeItemType.DERIVED_DATA, 1024, now)
                for name in names
            ]
        )
    else:
        ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), root)
        ui.items = [DiskItem(root / name, name, 1024, False, now) for name in names]
        ui.show_small_items = True
    ui.cursor = 38
    return ui


def render_view(provider, size):
    """Inspect the screen Prompt Toolkit actually paints, not a flattened surrogate."""
    stream = StringIO()
    output = Vt100_Output(
        stream,
        lambda: size,
        default_color_depth=ColorDepth.TRUE_COLOR,
        enable_cpr=False,
    )
    view = ViewLayout(provider)
    captured = {}
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
        app = TerminalApplication(layout=view.layout, input=pipe, output=output)

        def capture(current):
            if current.is_done:
                return
            info = view.body.render_info
            captured["visible"] = info.displayed_lines
            captured["cursor"] = info.ui_content.cursor_position.y
            painted = current.renderer._last_screen
            captured["text"] = [
                "".join(
                    painted.data_buffer[y][x].char for x in range(size.columns)
                ).rstrip()
                for y in range(size.rows)
            ]
            current.exit()

        app.after_render += capture
        app.run()
    return captured


@pytest.mark.parametrize(
    "kind", ["menu", "files", "projects", "caches", "xcode", "explorer"]
)
@pytest.mark.parametrize(
    "columns,rows", [(160, 50), (100, 30), (80, 24), (50, 18), (32, 12), (20, 6)]
)
def test_screens_fit_terminal_and_keep_focused_row(
    kind, columns, rows, tmp_path, monkeypatch
):
    monkeypatch.setattr(meters, "graphics_supported", lambda: False)
    ui = make_screen(kind, tmp_path)
    result = render_view(ui._get_content, Size(rows=rows, columns=columns))
    assert result["cursor"] in result["visible"]
    assert len(result["text"]) <= rows
    assert all(get_cwidth(line) <= columns for line in result["text"])
    if columns >= 32:
        assert any("038" in line for line in result["text"])
        if kind != "menu":
            assert any("Selected:" in line for line in result["text"])
    assert ui.cursor == 38


def test_table_uses_full_width_and_hides_secondary_columns(monkeypatch):
    size = Size(rows=30, columns=140)
    monkeypatch.setattr("yeet.ui.geometry.terminal_size", lambda: size)
    wide = responsive.table_columns(FILES)
    assert "path" in [column.key for column, _ in wide]
    assert "modified" in [column.key for column, _ in wide]
    assert get_cwidth(responsive.table_line(FILES)) == 134
    size = Size(rows=12, columns=32)
    narrow = responsive.table_columns(FILES)
    assert [column.key for column, _ in narrow] == ["select", "name", "size"]
    assert get_cwidth(responsive.table_line(FILES)) == 26


def test_explorer_overlays_resize_and_scroll(tmp_path, monkeypatch):
    ui = make_screen("explorer", tmp_path)
    ui.show_help = True
    ui.overlay_cursor = 19
    result = render_view(ui._get_content, Size(rows=12, columns=40))
    assert result["cursor"] in result["visible"]
    assert any("Quit explorer" in line for line in result["text"])
    assert any("Esc close" in line for line in result["text"])


@pytest.mark.parametrize("mechanism", ["poll", "signal"])
def test_live_resize_reallocates_surface_and_preserves_selection(
    tmp_path, monkeypatch, mechanism
):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    ui = make_screen("files", tmp_path)
    ui.selected = {2, 38}
    size = Size(rows=30, columns=100)
    font = (10, 20)
    monkeypatch.setattr(sessions, "cell_size", lambda _: font)
    stream = StringIO()
    output = Vt100_Output(
        stream,
        lambda: size,
        default_color_depth=ColorDepth.TRUE_COLOR,
        enable_cpr=False,
    )
    original_run = Application.run
    observed = []

    def run_with_resizes(app, *args, **kwargs):
        async def resize():
            nonlocal size, font
            try:
                phases = [
                    (100, 30, 10, 20, 10, 5),
                    (48, 16, 10, 20, 4, 2),
                    (140, 40, 10, 20, 10, 5),
                    (140, 40, 8, 18, 8, 5),
                ]
                for columns, rows, cw, ch, cell, pixel_rows in phases:
                    size = Size(rows=rows, columns=columns)
                    font = (cw, ch)
                    if mechanism == "signal":
                        app._on_resize()  # The callback Prompt Toolkit invokes on SIGWINCH.
                    expected = (
                        (columns - 4) * cw,
                        pixel_rows * ch,
                        columns - 4,
                        pixel_rows,
                    )
                    for _ in range(200):
                        geometry = app.session.presented_geometry
                        if (
                            geometry is not None
                            and (
                                geometry.width,
                                geometry.height,
                                geometry.columns,
                                geometry.rows,
                            )
                            == expected
                            and geometry.cell == cell
                        ):
                            break
                        await asyncio.sleep(0.01)
                    else:
                        raise AssertionError(f"No redraw for {columns}x{rows}")
                    observed.append(geometry)
                    assert ui.cursor == 38 and ui.selected == {2, 38}
                    view = ui._get_content()
                    assert "038" in "".join(text for _, text in view.row(view.cursor))
            finally:
                app.exit()

        kwargs["pre_run"] = lambda: app.create_background_task(resize())
        return original_run(app, *args, **kwargs)

    monkeypatch.setattr(Application, "run", run_with_resizes)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
        ui.run()
    assert len(observed) == 4
    # A resize creates the new geometry once; animation updates retain that resource.
    assert stream.getvalue().count("a=T,f=32") == 4
    balance = 0
    import re

    for operation in re.findall(r"\x1b\[\?2026([hl])", stream.getvalue()):
        balance += 1 if operation == "h" else -1
        assert balance in (0, 1)
    assert balance == 0


def test_multiline_filename_cannot_displace_the_focused_item(tmp_path, monkeypatch):
    monkeypatch.setattr(meters, "graphics_supported", lambda: False)
    now = datetime.now()
    names = [f"file-{i}" for i in range(10)]
    names[4] = "A\nB\nC\nD"
    names[5] = "FOCUSED"
    files = [LargeFile(tmp_path / name, name, 1024, now, now) for name in names]
    ui = DeletionItemSelector(files)
    ui.cursor = 5
    result = render_view(ui._get_content, Size(rows=12, columns=60))
    assert result["cursor"] in result["visible"]
    assert any("FOCUSED" in line for line in result["text"])
    assert (
        files[4].path.name == "A\nB\nC\nD"
    )  # Display escaping never changes filesystem identity.
