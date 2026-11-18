"""Storage proportions must stay honest while data and selections change."""

from datetime import datetime

from yeet.scanner import DiskExplorer
from yeet.ui.explorer import DiskExplorerUI
from yeet.ui.explorer_render import get_storage_overview
from yeet.ui.meter import ScanBreakdown, Segment, dot_meter
from yeet.utils import SIZE_LOADING, DiskItem


def plain(fragments):
    return "".join(text for _, text in fragments)


def test_proportions_leave_unknown_capacity_unlit():
    rendered = dot_meter([Segment("Known", 25, "#60a5fa")], 100, width=20, rows=1)
    assert plain(rendered).count("•") == 5
    assert plain(rendered).count("·") == 15


def test_empty_and_overfull_meters_keep_their_width():
    for total in (0, 5):
        rendered = dot_meter([Segment("Data", 100, "#60a5fa")], total, width=12, rows=2)
        assert all(len(row) == 14 for row in plain(rendered).splitlines())
    assert "•" not in plain(dot_meter([], 0))


def test_breakdown_sums_groups_and_preserves_all_measured_bytes():
    meter = ScanBreakdown([("Apps", 25), ("Videos", 75), ("Apps", 5)])
    assert meter.total == 105
    assert [(segment.label, segment.size) for segment in meter.segments] == [
        ("Videos", 75),
        ("Apps", 30),
    ]
    assert "Scan results · 105 B measured" in plain(meter.render())
    assert plain(meter.render("Apps")).count("•") > 0


def test_breakdown_other_preserves_small_groups_and_their_focus():
    meter = ScanBreakdown([(f"App-{i}", i + 1) for i in range(9)])
    assert sum(segment.size for segment in meter.segments) == sum(range(1, 10))
    assert len(meter.segments) == 6
    assert meter.group_indices["App-0"] == 5
    assert meter.color_for("App-0") == meter.segments[5].color


def test_partial_scan_does_not_count_loading_as_data(tmp_path, monkeypatch):
    explorer = DiskExplorer(min_size_bytes=0)
    ui = DiskExplorerUI(explorer, start_path=tmp_path)
    ui.items = [
        DiskItem(
            path=tmp_path / name,
            name=name,
            size=size,
            is_dir=True,
            modified=datetime.now(),
        )
        for name, size in [("Known", 25), ("Pending", SIZE_LOADING)]
    ]
    monkeypatch.setattr(explorer, "get_cached_size", lambda path: 100)
    # Filtering does not make measured data disappear from the overview.
    ui.filtered_items = []
    content = plain(get_storage_overview(ui))
    assert "Measuring 1 folder" in content
    assert "Known 25 B" in content
    assert "Unmeasured 75 B" in content
    assert "Pending" not in content
