"""Visual treemap showing how storage is distributed (WinDirStat style)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rich.console import Console
from rich.text import Text

from ..utils import format_size


# Colors for different categories
CATEGORY_COLORS = {
    # Browsers
    "Browser": "bright_blue",
    # Package managers
    "Package Manager": "bright_green",
    # Build tools
    "Build Tool": "bright_yellow",
    # Containers
    "Container": "bright_magenta",
    # IDEs
    "IDE/Editor": "bright_cyan",
    "IDE": "bright_cyan",
    # System
    "System": "red",
    # Runtime
    "Runtime": "yellow",
    # Project types
    "node": "bright_green",
    "python": "bright_yellow",
    "rust": "rgb(255,165,0)",
    "go": "bright_cyan",
    "git": "bright_magenta",
    "other": "bright_blue",
    # File extensions
    ".mp4": "bright_magenta",
    ".mov": "bright_magenta",
    ".avi": "bright_magenta",
    ".mkv": "bright_magenta",
    ".zip": "bright_yellow",
    ".tar": "bright_yellow",
    ".gz": "bright_yellow",
    ".dmg": "bright_cyan",
    ".iso": "bright_cyan",
    ".app": "bright_green",
    ".exe": "bright_green",
    # Default
    "Other": "blue",
    "default": "blue",
}

# Block characters
BLOCK_FULL = "█"
BLOCK_LIGHT = "░"


@dataclass
class SpaceItem:
    """An item taking up space."""

    name: str
    size: int
    category: str = ""


@dataclass
class Rect:
    """A rectangle in the treemap."""

    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


def _get_color(category: str) -> str:
    """Get color for a category."""
    # Try exact match
    if category in CATEGORY_COLORS:
        return CATEGORY_COLORS[category]
    # Try lowercase
    if category.lower() in CATEGORY_COLORS:
        return CATEGORY_COLORS[category.lower()]
    # Try as extension
    if category.startswith("."):
        return CATEGORY_COLORS.get(category.lower(), CATEGORY_COLORS["default"])
    return CATEGORY_COLORS["default"]


def _squarify(
    items: list[tuple[SpaceItem, float]],  # (item, normalized_size)
    rect: Rect,
) -> list[tuple[SpaceItem, Rect]]:
    """
    Squarified treemap algorithm.

    Attempt to create rectangles with aspect ratios close to 1.
    Returns list of (item, rect) pairs.
    """
    if not items or rect.width <= 0 or rect.height <= 0:
        return []

    if len(items) == 1:
        return [(items[0][0], rect)]

    results = []
    remaining_items = items[:]
    current_rect = Rect(rect.x, rect.y, rect.width, rect.height)

    while remaining_items and current_rect.width > 0 and current_rect.height > 0:
        # Decide split direction based on aspect ratio
        horizontal = current_rect.width >= current_rect.height

        # Take items for this row/column
        row_items = []
        row_size = 0.0
        total_remaining = sum(size for _, size in remaining_items)

        if total_remaining <= 0:
            break

        # Greedily add items to row while aspect ratio improves
        for item, size in remaining_items:
            test_row = row_items + [(item, size)]
            test_size = row_size + size

            if horizontal:
                row_length = (
                    int((test_size / total_remaining) * current_rect.width)
                    if total_remaining > 0
                    else 0
                )
                if row_length <= 0:
                    row_length = 1
            else:
                row_length = (
                    int((test_size / total_remaining) * current_rect.height)
                    if total_remaining > 0
                    else 0
                )
                if row_length <= 0:
                    row_length = 1

            # Calculate worst aspect ratio in this row
            if len(test_row) > 3 and row_length > 0:
                # Limit row size for better distribution
                break

            row_items.append((item, size))
            row_size += size

            if len(row_items) >= len(remaining_items):
                break

        if not row_items:
            break

        # Remove used items
        for item, size in row_items:
            remaining_items.remove((item, size))

        # Calculate row dimension
        if total_remaining > 0:
            if horizontal:
                row_width = max(
                    1, int((row_size / total_remaining) * current_rect.width)
                )
                row_height = current_rect.height
            else:
                row_width = current_rect.width
                row_height = max(
                    1, int((row_size / total_remaining) * current_rect.height)
                )
        else:
            break

        # Subdivide row among items
        if horizontal:
            # Stack vertically within the row
            y_offset = current_rect.y
            for item, size in row_items:
                item_height = (
                    max(1, int((size / row_size) * row_height)) if row_size > 0 else 1
                )
                item_height = min(item_height, current_rect.y + row_height - y_offset)
                if item_height > 0:
                    results.append(
                        (item, Rect(current_rect.x, y_offset, row_width, item_height))
                    )
                y_offset += item_height

            # Update remaining rect
            current_rect = Rect(
                current_rect.x + row_width,
                current_rect.y,
                current_rect.width - row_width,
                current_rect.height,
            )
        else:
            # Stack horizontally within the row
            x_offset = current_rect.x
            for item, size in row_items:
                item_width = (
                    max(1, int((size / row_size) * row_width)) if row_size > 0 else 1
                )
                item_width = min(item_width, current_rect.x + row_width - x_offset)
                if item_width > 0:
                    results.append(
                        (item, Rect(x_offset, current_rect.y, item_width, row_height))
                    )
                x_offset += item_width

            # Update remaining rect
            current_rect = Rect(
                current_rect.x,
                current_rect.y + row_height,
                current_rect.width,
                current_rect.height - row_height,
            )

    return results


def display_treemap(
    console: Console,
    items: Sequence[SpaceItem],
    title: str = "Space Distribution",
    width: int = 70,
    height: int = 15,
) -> None:
    """
    Display a WinDirStat-style treemap visualization.

    Each item gets a rectangle proportional to its size.
    Colors indicate category/type.

    Args:
        console: Rich console for output
        items: List of items with name and size
        title: Title for the display
        width: Width in characters
        height: Height in rows
    """
    if not items:
        console.print(f"\n[dim]No items to display[/]")
        return

    total_size = sum(item.size for item in items)
    if total_size == 0:
        console.print(f"\n[dim]No space used[/]")
        return

    # Sort by size descending
    sorted_items = sorted(items, key=lambda x: x.size, reverse=True)

    # Normalize sizes
    normalized = [(item, item.size / total_size) for item in sorted_items]

    # Create treemap layout
    root_rect = Rect(0, 0, width, height)
    layout = _squarify(normalized, root_rect)

    # Create the grid
    grid: list[list[tuple[str, str]]] = []  # (char, color)
    for _ in range(height):
        grid.append([(" ", "default")] * width)

    # Fill grid with rectangles
    item_rects: list[tuple[SpaceItem, Rect, str]] = []

    for item, rect in layout:
        color = _get_color(item.category)
        item_rects.append((item, rect, color))

        for y in range(rect.y, min(rect.y + rect.height, height)):
            for x in range(rect.x, min(rect.x + rect.width, width)):
                # Use different characters for borders vs fill
                is_top = y == rect.y
                is_bottom = y == rect.y + rect.height - 1
                is_left = x == rect.x
                is_right = x == rect.x + rect.width - 1

                if is_top or is_bottom or is_left or is_right:
                    # Border - slightly darker
                    grid[y][x] = (BLOCK_FULL, f"dim {color}")
                else:
                    # Fill
                    grid[y][x] = (BLOCK_FULL, color)

    # Render
    console.print()
    console.print(f"[bold]{title}[/] [dim]({format_size(total_size)} total)[/]")
    console.print()

    # Print grid
    for row in grid:
        line = Text()
        line.append("  ")  # Indent
        for char, color in row:
            line.append(char, style=color)
        console.print(line)

    console.print()

    # Legend - show top items with their colors
    console.print("  [bold]Legend:[/]")
    console.print()

    # Get unique items for legend (dedupe by name)
    seen = set()
    legend_items = []
    for item, rect, color in item_rects:
        if item.name not in seen and len(legend_items) < 10:
            seen.add(item.name)
            legend_items.append((item, color))

    # Two-column legend
    for i in range(0, len(legend_items), 2):
        item, color = legend_items[i]
        pct = (item.size / total_size) * 100
        name = item.name if len(item.name) <= 20 else item.name[:17] + "..."
        left = f"[{color}]{BLOCK_FULL}{BLOCK_FULL}[/] {name}: {format_size(item.size)} ({pct:.1f}%)"

        if i + 1 < len(legend_items):
            item2, color2 = legend_items[i + 1]
            pct2 = (item2.size / total_size) * 100
            name2 = item2.name if len(item2.name) <= 20 else item2.name[:17] + "..."
            right = f"[{color2}]{BLOCK_FULL}{BLOCK_FULL}[/] {name2}: {format_size(item2.size)} ({pct2:.1f}%)"
            console.print(f"  {left:<48} {right}")
        else:
            console.print(f"  {left}")

    # Show remaining
    if len(sorted_items) > 10:
        remaining = len(sorted_items) - 10
        remaining_size = sum(item.size for item in sorted_items[10:])
        console.print(
            f"\n  [dim]... and {remaining} more ({format_size(remaining_size)})[/]"
        )
