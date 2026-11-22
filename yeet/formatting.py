"""Formatting and parsing of user-facing sizes, ages and versions."""

from __future__ import annotations


def format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    if size_bytes < 0:
        return "0 B"

    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size:.1f} PB"


def format_days_ago(days: int | None) -> str:
    """Format days as relative time string."""
    if days is None:
        return "Never"
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years > 1 else ''} ago"


def parse_xcode_version(version_str: str) -> tuple[tuple[int, ...] | None, str | None]:
    """
    Parse Xcode device support version string.

    Examples:
        "17.0" -> ((17, 0), None)
        "17.0.1 (21B91)" -> ((17, 0, 1), "21B91")
        "17.0 (21A329) arm64e" -> ((17, 0), "21A329")
        "16.4.1 (20E252)" -> ((16, 4, 1), "20E252")

    Returns:
        Tuple of (version_tuple, build_string)
    """
    import re

    build_match = re.search(r"\(([^)]+)\)", version_str)
    build = build_match.group(1) if build_match else None

    version_match = re.match(r"(\d+(?:\.\d+)*)", version_str)
    if version_match:
        version_parts = version_match.group(1).split(".")
        version = tuple(int(p) for p in version_parts)
        return version, build

    return None, build
