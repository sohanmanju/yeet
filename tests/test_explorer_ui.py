"""Tests for DiskExplorerUI filtering and info behavior."""

from datetime import datetime

from yeet.scanner import DiskExplorer
from yeet.ui.explorer import DiskExplorerUI
from yeet.utils import DiskItem


def test_filter_matches_path(tmp_path):
    explorer = DiskExplorer(min_size_bytes=0)
    ui = DiskExplorerUI(explorer, start_path=tmp_path)

    item = DiskItem(
        path=tmp_path / "Nested" / "cache.bin",
        name="cache.bin",
        size=1024,
        is_dir=False,
        modified=datetime.now(),
    )
    ui.items = [item]
    ui.filter_text = "nested"

    ui._apply_filter()

    assert ui.filtered_items == [item]


def test_info_panel_shows_item_count(tmp_path):
    explorer = DiskExplorer(min_size_bytes=0)
    ui = DiskExplorerUI(explorer, start_path=tmp_path)

    parent = DiskItem(
        path=tmp_path,
        name=tmp_path.name,
        size=3_000,
        is_dir=True,
        modified=datetime.now(),
        item_count=2,
    )
    ui.items = [parent]

    info_text = "".join(fragment[1] for fragment in ui._get_item_info(parent))

    assert "Items:" in info_text
    assert "2" in info_text
