"""Tests for safety and history helpers."""

from io import StringIO
from pathlib import Path

from rich.console import Console

from yeet.config import Config
from yeet.history import make_history_entry, read_history, write_history_entry
from yeet.handlers.caches import perform_cache_deletions
from yeet.handlers.common import delete_item
from yeet.utils import CacheCategory, CacheLocation
from datetime import datetime
from yeet.safety import is_protected_path


def test_dry_run_does_not_delete_file():
    path = Path.cwd() / ".dry-run-test.txt"
    path.write_text("hello")

    try:
        success, msg = delete_item(path, use_trash=False, dry_run=True)

        assert success is True
        assert "Dry run" in msg
        assert path.exists()
    finally:
        if path.exists():
            path.unlink()


def test_protected_path_refuses_delete(tmp_path):
    path = tmp_path / "protected.txt"
    path.write_text("hello")

    config = Config(protected_paths=[str(path)])
    success, msg = delete_item(path, use_trash=False, config=config)

    assert success is False
    assert "Protected path" in msg
    assert path.exists()


def test_protected_path_blocks_descendant(tmp_path):
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
        dry_run=True,
        status="completed",
        selected_count=2,
        deleted_count=0,
        reclaimed_bytes=1234,
    )

    assert write_history_entry(entry, path=history_file)

    entries = read_history(path=history_file)
    assert len(entries) == 1
    assert entries[0]["workflow"] == "files"
    assert entries[0]["dry_run"] is True


def test_history_limit(tmp_path):
    history_file = tmp_path / "history.jsonl"

    for idx in range(3):
        write_history_entry(
            make_history_entry(f"run-{idx}", dry_run=False, status="completed"),
            path=history_file,
        )

    entries = read_history(path=history_file, limit=2)
    assert [entry["workflow"] for entry in entries] == ["run-1", "run-2"]


def test_contents_only_cache_deletion_keeps_parent(tmp_path):
    cache_dir = Path.cwd() / ".tmp-container-cache"
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

    console = Console(file=StringIO(), force_terminal=False, color_system=None)
    try:
        results = perform_cache_deletions(
            console, [cache], use_trash=False, dry_run=False
        )

        assert results[0][0] == cache
        assert results[0][1] is True
        assert cache_dir.exists()
        assert not child.exists()
    finally:
        if child.exists():
            child.unlink()
        if cache_dir.exists():
            cache_dir.rmdir()
