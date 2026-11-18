"""Stable folder-content categories, independent of file rank and cursor."""

from .meter import Segment, file_storage_group

# Match fix-storage's category language where it applies. Directories stay
# explicitly Folders: their contents have not been classified recursively.
COLORS = {
    "Apps": "#3b82f6",
    "Developer": "#22c55e",
    "Photos": "#ec4899",
    "Videos": "#8b5cf6",
    "Documents": "#22d3ee",
    "Music": "#eab308",
    "Archives": "#f59e0b",
    "Installers": "#f97316",
    "Folders": "#60a5fa",
    "Other files": "#9ca3af",
}


def storage_group(item) -> str:
    if item.is_dir:
        return "Folders"
    group = file_storage_group(item)
    return group if group in COLORS else "Other files"


def storage_segments(items) -> list[Segment]:
    sizes: dict[str, int] = {}
    for item in items:
        if item.size > 0:
            group = storage_group(item)
            sizes[group] = sizes.get(group, 0) + item.size
    return [
        Segment(group, sizes[group], color, id=group)
        for group, color in COLORS.items()
        if group in sizes
    ]
