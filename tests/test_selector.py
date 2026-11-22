"""Tests for the shared deletion selector."""

from datetime import datetime
from pathlib import Path

from yeet.ui.storage_model import file_storage_group
from yeet.ui.selector import DeletionItemSelector
from yeet.ui.selection_model import SelectionState
from yeet.utils import LargeFile, LeftoverItem


def test_selector_renders_leftover_items_without_extension():
    item = LeftoverItem(
        path=Path("/tmp/Slack"),
        name="Slack",
        source="Application Support",
        size=1024,
        last_modified=datetime.now(),
        app_hint="Slack Helper",
    )

    selector = DeletionItemSelector([item], title="App Leftovers")

    row_text = "".join(fragment[1] for fragment in selector.screen_view().row(0))

    assert "Slack" in row_text
    assert "Slack Helper" in row_text


def test_large_files_meter_is_inventory_not_deletion_selection():
    now = datetime.now()
    files = [
        LargeFile(Path(path), Path(path).name, size, now, now)
        for path, size in [
            ("/Applications/Slack.app/Contents/data.bin", 30),
            ("/Applications/Chrome.app/Contents/data.bin", 50),
            ("/Downloads/video.mov", 20),
        ]
    ]
    selector = DeletionItemSelector(files, title="Large Files")
    before = selector.screen_view()
    selector.restore_selection(
        SelectionState(frozenset({files[0].path, files[2].path}), files[2].path)
    )
    after = selector.screen_view()
    plain = lambda fragments: "".join(text for _, text in fragments)
    for view in (before, after):
        assert "Chrome 50 B" in plain(view.header)
        assert "Slack 30 B" in plain(view.header)
        assert "Videos 20 B" in plain(view.header)
        assert "100 B measured" in plain(view.header)
    assert "Selected: 0 files" in plain(before.footer)
    assert "Selected: 2 files (50 B)" in plain(after.footer)


def test_large_files_group_by_known_owner_or_file_category():
    now = datetime.now()
    files = [
        LargeFile(Path(path), Path(path).name, 10, now, now)
        for path in [
            "/Applications/Slack.app/Contents/data.bin",
            "/Downloads/report.pdf",
            "/Downloads/archive.zip",
            "/Downloads/unknown.bin",
        ]
    ]
    assert [file_storage_group(item) for item in files] == [
        "Slack",
        "Documents",
        "Archives",
        "Other files",
    ]


def test_selection_can_reach_and_select_the_entire_inventory():
    now = datetime.now()
    files = [
        LargeFile(Path(f"/tmp/file-{i}"), f"file-{i}", 1, now, now) for i in range(50)
    ]
    ui = DeletionItemSelector(files)
    for _ in range(49):
        ui.move(1)
    ui.toggle()
    assert ui.selection_state().focused_path == files[49].path
    assert ui.selection_state().selected_paths == frozenset({files[49].path})
    ui.select_all()
    assert ui.selection_state().selected_paths == frozenset(file.path for file in files)


def test_grouped_xcode_rows_keep_stable_item_ids_and_bulk_selection_policy():
    from yeet.ui.selector import XcodeSelector
    from yeet.utils import XcodeItem, XcodeItemType

    now = datetime.now()
    items = [
        XcodeItem(
            Path("/tmp/new"), "New", XcodeItemType.DERIVED_DATA, 50, now, is_latest=True
        ),
        XcodeItem(Path("/tmp/old"), "Old", XcodeItemType.DEVICE_SUPPORT, 20, now),
    ]
    ui = XcodeSelector(items)
    assert ui.focused_path == items[1].path
    ui.toggle()
    assert ui.selection_state().selected_paths == frozenset({items[1].path})
    ui.move(1)
    ui.toggle()
    assert ui.selection_state().selected_paths == frozenset(
        {items[0].path, items[1].path}
    )
    ui.select_all()
    assert ui.selection_state().selected_paths == frozenset({items[1].path})


def test_selection_state_restores_by_path_after_inventory_reordering(tmp_path):
    from datetime import datetime
    from yeet.models import LargeFile
    from yeet.ui.selector import DeletionItemSelector
    from yeet.ui.selection_model import SelectionState

    now = datetime.now()
    a, b, c = [
        LargeFile(tmp_path / name, name, 10, now, now) for name in ("a", "b", "c")
    ]
    original = DeletionItemSelector([a, b, c])
    original.restore_selection(SelectionState(frozenset({a.path, c.path}), b.path))
    refreshed = DeletionItemSelector([c, b])
    refreshed.restore_selection(original.selection_state())
    state = refreshed.selection_state()
    assert state.selected_paths == frozenset({c.path})
    assert state.focused_path == b.path
