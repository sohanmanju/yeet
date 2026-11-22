"""Append-only cleanup history storage."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from pathlib import Path


def get_history_path() -> Path:
    return Path.home() / ".config" / "yeet" / "history.jsonl"


def write_history_entry(entry: dict, path: Path | None = None) -> bool:
    """Append a history entry to disk."""
    history_path = path or get_history_path()

    try:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return True
    except OSError:
        return False


def make_history_entry(
    workflow: str,
    *,
    status: str,
    selected_count: int = 0,
    deleted_count: int = 0,
    reclaimed_bytes: int = 0,
    scanned_count: int | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a normalized history record."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "workflow": workflow,
        "status": status,
        "selected_count": selected_count,
        "deleted_count": deleted_count,
        "reclaimed_bytes": reclaimed_bytes,
    }
    if scanned_count is not None:
        entry["scanned_count"] = scanned_count
    if extra:
        entry.update(extra)
    return entry


def read_history(path: Path | None = None, limit: int | None = None) -> list[dict]:
    """Read history entries from disk."""
    history_path = path or get_history_path()
    if not history_path.exists():
        return []
    if limit == 0:
        return []

    try:
        if limit is not None and limit > 0:
            entries: deque[dict] = deque(maxlen=limit)
        else:
            entries = deque()

        with history_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    return list(entries)
