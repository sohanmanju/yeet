"""Behavior at shared filesystem and scan boundaries."""

import os
import subprocess
from datetime import datetime

from yeet.filesystem import directory_stats
from yeet.scanners.disk import DiskExplorer


def test_directory_stats_counts_nested_files_and_latest_modification(tmp_path):
    (tmp_path / "nested").mkdir()
    first = tmp_path / "first"
    second = tmp_path / "nested" / "second"
    first.write_bytes(b"abc")
    second.write_bytes(b"defgh")
    os.utime(tmp_path, (1000, 1000))
    os.utime(first, (2000, 2000))
    os.utime(second, (3000, 3000))
    stats = directory_stats(tmp_path)
    assert stats.size == 8
    assert stats.file_count == 2
    assert stats.last_modified == datetime.fromtimestamp(3000)


def test_deleting_nested_path_invalidates_ancestor_and_descendant_totals(tmp_path):
    explorer = DiskExplorer()
    nested = tmp_path / "project" / "build"
    unrelated = tmp_path / "other"
    for path in (tmp_path, nested.parent, nested, nested / "deeper", unrelated):
        path.mkdir(parents=True, exist_ok=True)
        explorer.calculate_size(path)
    explorer.invalidate_cache(nested)
    assert explorer.get_cached_size(unrelated) is not None
    for path in (tmp_path, nested.parent, nested, nested / "deeper"):
        assert explorer.get_cached_size(path) is None


def test_timed_out_size_process_is_killed_and_reaped(tmp_path, monkeypatch):
    class Process:
        killed = False
        reaped = False

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("du", timeout)
            self.reaped = True
            return "", ""

        def kill(self):
            self.killed = True

    proc = Process()
    monkeypatch.setattr("yeet.scanners.disk.subprocess.Popen", lambda *a, **kw: proc)
    explorer = DiskExplorer()
    assert explorer.calculate_size(tmp_path) == 0
    assert proc.killed and proc.reaped
    assert explorer.kill_active_processes() == 0


def test_xcode_scan_keeps_latest_versions_by_category_and_platform(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from yeet.models import XcodeItemType
    from yeet.scanners.xcode import XcodeScanner

    scanner = XcodeScanner()
    scanner.home = tmp_path
    for platform, version in (
        ("iOS", "17.0"),
        ("iOS", "18.0"),
        ("iOS", "18.0 (22A1)"),
        ("watchOS", "10.0"),
    ):
        path = (
            tmp_path
            / "Library"
            / "Developer"
            / "Xcode"
            / f"{platform} DeviceSupport"
            / version
        )
        path.mkdir(parents=True)
    monkeypatch.setattr("yeet.scanners.xcode.is_macos", lambda: True)
    monkeypatch.setattr(
        "yeet.scanners.xcode.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout="iOS 26.0 (23A1) - AABB-CCDD\nSize: 1G\nDeletable: YES\n",
        ),
    )
    results = scanner.scan()
    support = [
        item for item in results.items if item.item_type == XcodeItemType.DEVICE_SUPPORT
    ]
    assert {item.name for item in support if item.is_latest} == {
        "18.0",
        "18.0 (22A1)",
        "10.0",
    }
    assert next(item for item in support if item.name == "17.0").is_latest is False
    runtime = next(
        item
        for item in results.items
        if item.item_type == XcodeItemType.SIMULATOR_RUNTIME
    )
    assert runtime.is_latest
    assert runtime.version == (26, 0)


def test_invalidated_measurement_cannot_repopulate_cache(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from types import SimpleNamespace

    for invalidate in (
        lambda explorer: explorer.invalidate_cache(tmp_path),
        lambda explorer: explorer.clear_cache(),
    ):
        started, release = Event(), Event()

        class OldMeasurement:
            def communicate(self, timeout=None):
                started.set()
                assert release.wait(5)
                return "123\told measurement", ""

        fresh = SimpleNamespace(
            communicate=lambda **kwargs: ("2\tfresh measurement", "")
        )
        processes = iter([OldMeasurement(), fresh])
        monkeypatch.setattr(
            "yeet.scanners.disk.subprocess.Popen",
            lambda *args, **kwargs: next(processes),
        )
        explorer = DiskExplorer()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(explorer.calculate_size, tmp_path)
            try:
                assert started.wait(5)
                invalidate(explorer)
            finally:
                release.set()
            assert result.result(timeout=5) == 123 * 1024
        assert explorer.get_cached_size(tmp_path) is None
        assert explorer.calculate_size(tmp_path) == 2 * 1024
        assert explorer.get_cached_size(tmp_path) == 2 * 1024
