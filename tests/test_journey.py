"""Real terminal rendering and navigation of the cleanup journey."""

from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from tests.test_responsive_ui import render_view
from yeet.handlers.workflow import ScanBatch
from yeet.ui.journey import (
    ReviewItem,
    ReviewScreen,
    ResultsScreen,
    BusyScreen,
    choose_directory,
)


@pytest.mark.parametrize(
    "columns,rows", [(160, 50), (80, 24), (50, 18), (32, 12), (20, 6)]
)
@pytest.mark.parametrize("kind", ["review", "results"])
def test_journey_keeps_focused_item_and_actions_visible(columns, rows, kind):
    items = [ReviewItem(Path(f"/data/{i:03}-archive.zip"), 1024) for i in range(40)]
    page = (
        ReviewScreen(items, True)
        if kind == "review"
        else ResultsScreen([(item, False, "Permission denied") for item in items], True)
    )
    page.cursor = 38
    captured = render_view(page._get_content, Size(rows=rows, columns=columns))
    assert captured["cursor"] in captured["visible"]
    assert any("038" in line for line in captured["text"])
    assert any("[ " in line for line in captured["text"])


def terminal_input(keys, run):
    output = Vt100_Output(
        StringIO(), lambda: Size(rows=24, columns=80), enable_cpr=False
    )
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
        pipe.send_text(keys)
        return run()


def test_review_defaults_to_back_and_requires_action_change():
    items = [ReviewItem(Path("/data/file"), 1)]
    assert terminal_input("\r", ReviewScreen(items, False).run) == "back"
    assert terminal_input("\t\r", ReviewScreen(items, False).run) == "confirm"


def test_directory_entry_and_background_progress(tmp_path):
    assert (
        terminal_input("\r", lambda: choose_directory(tmp_path)) == tmp_path.resolve()
    )
    assert terminal_input("\x1b", lambda: choose_directory(tmp_path)) is None
    assert (
        terminal_input(
            "",
            lambda: BusyScreen("Scanning").run(lambda update: (update("Done"), 42)[1]),
        )
        == 42
    )


def test_results_distinguish_trash_and_failures():
    item = ReviewItem(Path("/data/file"), 1024)
    page = ResultsScreen(
        [(item, True, "Moved"), (item, False, "Permission denied")], True
    )
    assert "Space recovered" not in page.summary
    assert "Moved to Trash" in page.summary
    captured = render_view(page._get_content, Size(rows=24, columns=80))
    assert any("Failed · Permission denied" in line for line in captured["text"])


def test_session_preserves_cancelled_selection_and_reselects_failures(
    tmp_path, monkeypatch
):
    import yeet.handlers.session as session
    from yeet.config import Config
    from yeet.ui.selector import DeletionItemSelector
    from yeet.utils import LargeFile

    now = datetime.now()
    files = [LargeFile(tmp_path / name, name, 1024, now, now) for name in ("a", "b")]
    monkeypatch.setattr(session, "get_config", lambda: Config(use_trash=True))
    monkeypatch.setattr(session, "trash_available", lambda: True)
    monkeypatch.setattr(session, "record_history", lambda *a, **kw: True)
    monkeypatch.setattr(session, "record_cleanup", lambda *a, **kw: True)
    monkeypatch.setattr(BusyScreen, "run", lambda self, work: work(lambda *_: None))
    reviews = iter(["back", "confirm"])
    monkeypatch.setattr(ReviewScreen, "run", lambda self: next(reviews))
    monkeypatch.setattr(ResultsScreen, "run", lambda self: "continue")
    seen = []

    def select(self):
        seen.append(self)
        if len(seen) == 1:
            self.selected = {0, 1}
            self.cursor = 1
        elif len(seen) == 2:
            state = self.selection_state()
            assert state.selected_paths == frozenset(file.path for file in files)
            assert state.focused_path == files[1].path
        else:
            assert self.selection_state().selected_paths == frozenset({files[1].path})
            self.cancelled = True
            return []
        return [row.value for row in self.rows if row.index in self.selected]

    monkeypatch.setattr(DeletionItemSelector, "run", select)
    scans = iter([ScanBatch(files, 2, [], {}), ScanBatch([files[1]], 1, [], {})])
    session.run_scan_workflow(
        None,
        SimpleNamespace(directory=str(tmp_path), json=False),
        key="files",
        title="Files",
        scan=lambda *_: next(scans),
        selector=DeletionItemSelector,
        delete=lambda item, trash: (
            item == files[0],
            "Done" if item == files[0] else "Permission denied",
        ),
    )
    assert len(seen) == 3


def test_inline_deletion_retains_list_layout(tmp_path):
    from yeet.ui.selector import DeletionItemSelector
    from yeet.utils import LargeFile

    now = datetime.now()
    files = [LargeFile(tmp_path / name, name, 1024, now, now) for name in ("a", "b")]
    host = DeletionItemSelector(files, "Large Files")
    host.selected = {0}
    before = host.screen_view()
    page = ReviewScreen([ReviewItem(files[0].path, 1024)], True).within(host)
    inline = page._get_content()
    assert inline.header == before.header
    assert inline.count == before.count
    assert inline.row(1) == before.row(1)
    terminal_input("j\r", page.run)
    assert host.focused_path == files[1].path
    assert host.selection_state().selected_paths == frozenset({files[0].path})
    assert terminal_input("\r", page.run) == "back"
    assert host.selection_state().selected_paths == frozenset({files[0].path})
    busy = BusyScreen("Moving to Trash").within(host)._get_content()
    assert busy.header == host.screen_view().header
    assert busy.count == before.count


def test_cancelled_directory_picker_retains_empty_results_page(tmp_path, monkeypatch):
    import yeet.handlers.session as session
    from yeet.ui.journey import JourneyPage

    monkeypatch.setattr(BusyScreen, "run", lambda self, work: work(lambda *_: None))
    monkeypatch.setattr(session, "record_history", lambda *a, **kw: True)
    monkeypatch.setattr(session, "choose_directory", lambda *_: None)
    pages = []
    actions = iter(["directory", "menu"])

    def choose(page):
        pages.append(page)
        return next(actions)

    monkeypatch.setattr(JourneyPage, "run", choose)
    scans = []

    def scan(root, progress):
        scans.append(root)
        return ScanBatch([], 0, ["inaccessible folder"], {})

    session.run_scan_workflow(
        None,
        SimpleNamespace(directory=str(tmp_path), json=False),
        key="files",
        title="Files",
        scan=scan,
        selector=None,
    )
    assert scans == [tmp_path.resolve()]
    assert len(pages) == 2
    assert pages[0].summary == pages[1].summary
    assert "1 scan errors" in pages[1].note


@pytest.mark.parametrize("host_kind", ["selector", "explorer"])
def test_inline_results_follow_host_focus_even_when_outcomes_are_reordered(
    tmp_path, host_kind
):
    from prompt_toolkit.formatted_text import fragment_list_to_text
    from yeet.models import LargeFile, DiskItem
    from yeet.ui.selector import DeletionItemSelector
    from yeet.ui.explorer import DiskExplorerUI
    from yeet.scanners.disk import DiskExplorer

    now = datetime.now()
    paths = [tmp_path / name for name in ("a", "b", "c")]
    if host_kind == "selector":
        host = DeletionItemSelector(
            [LargeFile(path, path.name, 10, now, now) for path in paths]
        )
    else:
        host = DiskExplorerUI(DiskExplorer(min_size_bytes=0), start_path=tmp_path)
        host.items = [DiskItem(path, path.name, 10, False, now) for path in paths]
    page = ResultsScreen(
        [
            (ReviewItem(paths[0], 10), True, "Moved successfully"),
            (ReviewItem(paths[1], 10), False, "First failure"),
            (ReviewItem(paths[2], 10), False, "Second failure"),
        ],
        True,
    ).within(host)
    assert "Moved successfully" in fragment_list_to_text(page._get_content().footer)
    for path, message in zip(paths[1:], ("First failure", "Second failure")):
        terminal_input("j\r", page.run)
        footer = fragment_list_to_text(page._get_content().footer)
        assert host.focused_path == path
        assert message in footer
    assert "First failure" not in footer
