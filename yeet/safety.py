"""Path safety helpers for cleanup workflows."""

from __future__ import annotations

from pathlib import Path

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


def _matches_prefix(path: Path, candidate: Path) -> bool:
    return path == candidate or candidate in path.parents


def is_protected_path(path: Path, config: Config | None = None) -> bool:
    """Return True when a path should not be deleted."""
    normalized = _normalize(path)

    # Configured protected paths are exact-match or descendants.
    if config is not None:
        for raw in config.protected_paths:
            candidate = _normalize(Path(raw))
            if _matches_prefix(normalized, candidate):
                return True

    # Built-in danger rules mirror the explorer warnings.
    for candidate in BUILTIN_DANGEROUS_PATHS:
        if _matches_prefix(normalized, candidate):
            return True

    return False


def is_ignored_path(path: Path, config: Config | None = None) -> bool:
    """Return True when a path should be skipped during scans."""
    if config is None:
        return False

    normalized = _normalize(path)
    for raw in config.ignored_paths:
        candidate = _normalize(Path(raw))
        if _matches_prefix(normalized, candidate):
            return True
    return False
