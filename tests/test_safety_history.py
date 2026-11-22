"""Tests for safety and history helpers."""

from pathlib import Path

from yeet.config import Config
from yeet.history import make_history_entry, read_history, write_history_entry
from yeet.handlers.caches import delete_cache
from yeet.handlers.common import delete_item
from yeet.utils import CacheCategory, CacheLocation
from datetime import datetime
from yeet.safety import is_protected_path


def test_unavailable_trash_does_not_delete_file(tmp_path, monkeypatch):
    import yeet.handlers.common as common

    path = tmp_path / "keep.txt"
    path.write_text("hello")
    monkeypatch.setattr(common, "is_protected_path", lambda *_: False)
    monkeypatch.setattr(common, "trash_available", lambda: False)
    success, message = delete_item(path, use_trash=True)
    assert not success
    assert "Trash is unavailable" in message
    assert path.read_text() == "hello"


def test_protected_path_refuses_delete(tmp_path, monkeypatch):
    monkeypatch.setattr("yeet.safety.BUILTIN_DANGEROUS_PATHS", ())
    path = tmp_path / "protected.txt"
    path.write_text("hello")

    config = Config(protected_paths=[str(path)])
    success, msg = delete_item(path, use_trash=False, config=config)

    assert success is False
    assert "Protected path" in msg
    assert path.exists()


def test_protected_path_blocks_descendant(tmp_path, monkeypatch):
    monkeypatch.setattr("yeet.safety.BUILTIN_DANGEROUS_PATHS", ())
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child.txt"
    child.write_text("hello")

    config = Config(protected_paths=[str(parent)])
    success, msg = delete_item(child, use_trash=False, config=config)

    assert success is False
    assert "Protected path" in msg
    assert child.exists()


def test_builtin_protected_path_blocks_descendant():
    assert is_protected_path(Path("/usr/local/bin/tool")) is True


def test_history_round_trip(tmp_path):
    history_file = tmp_path / "history.jsonl"
    entry = make_history_entry(
        "files",
        status="completed",
        selected_count=2,
        deleted_count=0,
        reclaimed_bytes=1234,
    )

    assert write_history_entry(entry, path=history_file)

    entries = read_history(path=history_file)
    assert len(entries) == 1
    assert entries[0]["workflow"] == "files"


def test_history_limit(tmp_path):
    history_file = tmp_path / "history.jsonl"

    for idx in range(3):
        write_history_entry(
            make_history_entry(f"run-{idx}", status="completed"),
            path=history_file,
        )

    entries = read_history(path=history_file, limit=2)
    assert [entry["workflow"] for entry in entries] == ["run-1", "run-2"]


def test_contents_only_cache_deletion_keeps_parent(tmp_path, monkeypatch):
    import yeet.handlers.caches as caches
    import yeet.handlers.common as common

    # macOS resolves pytest's temporary root below the protected /private tree.
    monkeypatch.setattr(caches, "is_protected_path", lambda *_: False)
    monkeypatch.setattr(common, "is_protected_path", lambda *_: False)
    cache_dir = tmp_path / "container-cache"
    cache_dir.mkdir()
    child = cache_dir / "cache.bin"
    child.write_text("hello")
    cache = CacheLocation(
        path=cache_dir,
        name="Sandboxed App Cache",
        category=CacheCategory.CONTAINER,
        size=child.stat().st_size,
        file_count=1,
        last_modified=datetime.now(),
        delete_contents_only=True,
    )
    success, message = delete_cache(cache, False, Config())
    assert success, message
    assert cache_dir.is_dir()
    assert list(cache_dir.iterdir()) == []


def test_legacy_history_stays_readable(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text('{"workflow": "files", "dry_run": true, "deleted_count": 0}\n')
    assert read_history(path)[0]["dry_run"] is True


def test_windows_missing_trash_dependency_never_deletes(tmp_path, monkeypatch):
    import sys
    from yeet.utils import _trash_windows

    path = tmp_path / "keep.txt"
    path.write_text("keep")
    monkeypatch.setitem(sys.modules, "send2trash", None)
    success, message = _trash_windows(path)
    assert not success
    assert "Trash unavailable" in message
    assert path.read_text() == "keep"


def test_cleanup_accounting_separates_trash_from_reclaimed_bytes(tmp_path, monkeypatch):
    import yeet.handlers.common as common
    from yeet.ui.journey import ReviewItem

    entries = []
    monkeypatch.setattr(
        common, "write_history_entry", lambda entry: entries.append(entry) or True
    )
    outcomes = [
        (ReviewItem(tmp_path / "done", 100), True, "Done"),
        (ReviewItem(tmp_path / "failed", 200), False, "Denied"),
    ]
    for use_trash in (False, True):
        assert common.record_cleanup("files", outcomes, use_trash, scanned_count=10)
        entry = entries[-1]
        assert entry["selected_count"] == 2
        assert entry["deleted_count"] == 1
        assert entry["scanned_count"] == 10
        assert entry["reclaimed_bytes"] == (0 if use_trash else 100)
        assert entry["moved_bytes"] == (100 if use_trash else 0)
