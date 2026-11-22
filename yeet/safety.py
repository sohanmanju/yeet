"""Path safety helpers for cleanup workflows."""

from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

BUILTIN_DANGEROUS_PATHS = (
    Path("/System"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/var"),
    Path("/etc"),
    Path("/Applications"),
    Path("/Library"),
    Path("/private"),
    Path("/Users/Shared"),
    Path("/.Spotlight-V100"),
    Path("/.fseventsd"),
    Path("/cores"),
    Path("/opt"),
)


def _normalize(path: Path) -> Path:
    return path.expanduser().resolve()


def matches_path(path: Path, candidate: Path) -> bool:
    return path == candidate or candidate in path.parents


def is_protected_path(path: Path, config: Config | None = None) -> bool:
    """Return True when a path should not be deleted."""
    normalized = _normalize(path)

    if config is not None:
        for raw in config.protected_paths:
            candidate = _normalize(Path(raw))
            if matches_path(normalized, candidate):
                return True

    for candidate in BUILTIN_DANGEROUS_PATHS:
        if matches_path(normalized, candidate):
            return True

    return False
