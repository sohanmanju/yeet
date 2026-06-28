"""Tests for safety and history helpers."""

from pathlib import Path

from yeet.config import Config
from yeet.history import make_history_entry, read_history, write_history_entry
from yeet.handlers.common import delete_item
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
