"""Tests for the shared deletion selector."""

from datetime import datetime
from pathlib import Path

from yeet.ui.meter import file_storage_group
from yeet.ui.selector import DeletionItemSelector
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

    row_text = "".join(fragment[1] for fragment in selector._get_row(0))

    assert "Slack" in row_text
    assert "Slack Helper" in row_text


def test_selector_keeps_cursor_and_footer_visible_below_meter():
    items = [
        LeftoverItem(
            path=Path(f"/tmp/App-{i:02}"),
            name=f"App-{i:02}",
            source="Caches",
            size=1024,
            last_modified=datetime.now(),
            app_hint="Helper",
        )
        for i in range(40)
    ]
    selector = DeletionItemSelector(items)
    selector.cursor = 39
    view = selector._get_content()
    content = "".join(text for _, text in [*view.footer, *view.row(view.cursor)])
    assert "App-39" in content
    assert "Selected: 0 files" in content
    assert "Rows " in content


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
    before = selector._get_content()
    initial_segments = tuple(selector.meter.segments)
    initial_group = selector.rows[selector.cursor].group
    selector.cursor = 2
    selector.selected = {0, 2}
    after = selector._get_content()
    assert tuple(selector.meter.segments) == initial_segments
    assert selector.meter.total == 100
    assert {segment.label: segment.size for segment in initial_segments} == {
        "Chrome": 50,
        "Slack": 30,
        "Videos": 20,
    }
    assert initial_group != selector.rows[selector.cursor].group
    assert "Selected: 0 files" in "".join(text for _, text in before.footer)
    assert "Selected: 2 files (50 B)" in "".join(text for _, text in after.footer)


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


def test_selection_can_reach_items_beyond_the_old_display_limit():
    now = datetime.now()
    files = [
        LargeFile(Path(f"/tmp/file-{i}"), f"file-{i}", 1, now, now) for i in range(50)
    ]
    ui = DeletionItemSelector(files)
    for _ in range(49):
        ui.move(1)
    ui.toggle()
    assert ui.cursor == 49 and ui.selected == {49}
    ui.select_all()
    assert ui.selected == set(range(50))


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
    assert (
        ui.rows[0].value is items[1]
    )  # Display grouping differs from original item order.
    ui.toggle()
    assert ui.selected == {1}
    ui.move(1)
    ui.toggle()
    assert ui.selected == {0, 1}
    ui.select_all()
    assert ui.selected == {1}  # Latest stays out of the bulk action.
