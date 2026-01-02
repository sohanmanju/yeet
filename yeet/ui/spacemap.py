"""Visual space map showing how storage is distributed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box

from ..utils import format_size


# Block characters for the bar
BLOCK_FULL = "█"
BLOCK_CHARS = ["█", "▓", "▒", "░"]

# Colors for different categories/items (cycling through)
COLORS = [
    "bright_blue",
    "bright_green",
    "bright_yellow",
    "bright_magenta",
    "bright_cyan",
    "bright_red",
    "blue",
    "green",
    "yellow",
    "magenta",
    "cyan",
    "red",
]


@dataclass
class SpaceItem:
    """An item taking up space."""

    name: str
    size: int
    category: str = ""


def create_space_bar(
    items: Sequence[SpaceItem],
    width: int = 60,
) -> tuple[Text, list[tuple[str, str, int]], int]:
    """
    Create a horizontal bar showing space distribution.

    Args:
        items: List of items with name and size
        width: Width of the bar in characters

    Returns:
        Tuple of (bar Text, legend items, total size)
    """
    if not items:
        return Text("No items to display", style="dim"), [], 0

    total_size = sum(item.size for item in items)
    if total_size == 0:
        return Text("No space used", style="dim"), [], 0

    # Sort by size descending
    sorted_items = sorted(items, key=lambda x: x.size, reverse=True)

    # Build the bar
    bar = Text()
    legend_items: list[tuple[str, str, int]] = []  # (color, name, size)

    remaining_width = width
    for i, item in enumerate(sorted_items):
        color = COLORS[i % len(COLORS)]

        # Calculate width for this item (proportional to size)
        proportion = item.size / total_size
        item_width = max(1, int(proportion * width)) if proportion > 0.01 else 0

        # Don't exceed remaining width
        item_width = min(item_width, remaining_width)

        if item_width > 0:
            bar.append(BLOCK_FULL * item_width, style=color)
            remaining_width -= item_width
            legend_items.append((color, item.name, item.size))

    # Fill any remaining space (due to rounding)
    if remaining_width > 0 and legend_items:
        bar.append(BLOCK_FULL * remaining_width, style=legend_items[0][0])

    return bar, legend_items, total_size


def display_space_map(
    console: Console,
    items: Sequence[SpaceItem],
    title: str = "Space Distribution",
    width: int = 70,
    max_legend_items: int = 10,
) -> None:
    """
    Display a visual space map with legend.

    Args:
        console: Rich console for output
        items: List of items with name and size
        title: Title for the display
        width: Width of the bar
        max_legend_items: Maximum items to show in legend
    """
    if not items:
        console.print(f"\n[dim]No items to display for {title}[/]")
        return

    bar, legend_items, total_size = create_space_bar(items, width=width)

    # Create the display
    console.print()

    # Title and total
    console.print(f"[bold]{title}[/] [dim]({format_size(total_size)} total)[/]")
    console.print()

    # The bar
    console.print("  ", end="")
    console.print(bar)
    console.print()

    # Legend as a compact table
    if legend_items:
        # Show top items
        display_items = legend_items[:max_legend_items]
        other_size = sum(size for _, _, size in legend_items[max_legend_items:])

        # Create two-column legend for compactness
        left_col = []
        right_col = []

        for i, (color, name, size) in enumerate(display_items):
            percentage = (size / total_size) * 100
            # Truncate long names
            display_name = name if len(name) <= 24 else name[:21] + "..."
            entry = f"[{color}]{BLOCK_FULL}[/] {display_name}: [bold]{format_size(size)}[/] [dim]({percentage:.1f}%)[/]"

            if i % 2 == 0:
                left_col.append(entry)
            else:
                right_col.append(entry)

        # Print legend in two columns
        for i in range(max(len(left_col), len(right_col))):
            left = left_col[i] if i < len(left_col) else ""
            right = right_col[i] if i < len(right_col) else ""
            if right:
                console.print(f"  {left:<50} {right}")
            else:
                console.print(f"  {left}")

        # Show "other" category if there are more items
        if other_size > 0:
            other_count = len(legend_items) - max_legend_items
            percentage = (other_size / total_size) * 100
            console.print(
                f"  [dim]{BLOCK_FULL} +{other_count} others: {format_size(other_size)} ({percentage:.1f}%)[/]"
            )


def display_category_breakdown(
    console: Console,
    items: Sequence[SpaceItem],
    title: str = "Space by Category",
    width: int = 70,
) -> None:
    """
    Display space map grouped by category.

    Args:
        console: Rich console for output
        items: List of items with name, size, and category
        title: Title for the display
        width: Width of the bar
    """
    if not items:
        console.print(f"\n[dim]No items to display for {title}[/]")
        return

    # Group by category
    categories: dict[str, int] = {}
    for item in items:
        cat = item.category or "Other"
        categories[cat] = categories.get(cat, 0) + item.size

    # Convert to SpaceItems
    category_items = [
        SpaceItem(name=cat, size=size) for cat, size in categories.items()
    ]

    display_space_map(console, category_items, title=title, width=width)


def display_horizontal_bars(
    console: Console,
    items: Sequence[SpaceItem],
    title: str = "Space Usage",
    max_items: int = 15,
    bar_width: int = 30,
) -> None:
    """
    Display horizontal bar chart for each item.

    Args:
        console: Rich console for output
        items: List of items with name and size
        title: Title for the display
        max_items: Maximum number of items to show
        bar_width: Width of each bar
    """
    if not items:
        console.print(f"\n[dim]No items to display[/]")
        return

    sorted_items = sorted(items, key=lambda x: x.size, reverse=True)[:max_items]
    max_size = sorted_items[0].size if sorted_items else 0
    total_size = sum(item.size for item in items)

    console.print()
    console.print(f"[bold]{title}[/] [dim]({format_size(total_size)} total)[/]")
    console.print()

    # Find max name length for alignment
    max_name_len = min(25, max(len(item.name) for item in sorted_items))

    for i, item in enumerate(sorted_items):
        color = COLORS[i % len(COLORS)]

        # Calculate bar width
        proportion = item.size / max_size if max_size > 0 else 0
        filled = int(proportion * bar_width)

        # Truncate name
        name = (
            item.name
            if len(item.name) <= max_name_len
            else item.name[: max_name_len - 3] + "..."
        )

        # Build bar
        bar = f"[{color}]{BLOCK_FULL * filled}[/][dim]{'░' * (bar_width - filled)}[/]"

        # Percentage of total
        pct = (item.size / total_size * 100) if total_size > 0 else 0

        console.print(
            f"  {name:<{max_name_len}} {bar} [bold]{format_size(item.size):>9}[/] [dim]({pct:5.1f}%)[/]"
        )

    # Show count of remaining items
    remaining = len(items) - max_items
    if remaining > 0:
        remaining_size = sum(
            item.size
            for item in sorted(items, key=lambda x: x.size, reverse=True)[max_items:]
        )
        console.print(
            f"\n  [dim]... and {remaining} more ({format_size(remaining_size)})[/]"
        )
