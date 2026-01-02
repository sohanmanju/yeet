"""Visual space map (treemap/heatmap) showing how storage is distributed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rich.console import Console
from rich.text import Text

from ..utils import format_size


# Block character for cells
BLOCK = "█"

# Heat colors from cool (small) to hot (large)
HEAT_COLORS = [
    "bright_blue",  # Coolest - smallest
    "cyan",
    "bright_cyan",
    "green",
    "bright_green",
    "yellow",
    "bright_yellow",
    "rgb(255,165,0)",  # Orange
    "bright_red",
    "red",  # Hottest - largest
]


@dataclass
class SpaceItem:
    """An item taking up space."""

    name: str
    size: int
    category: str = ""


def _get_heat_color(proportion: float) -> str:
    """Get color based on proportion (0.0 to 1.0)."""
    idx = min(int(proportion * len(HEAT_COLORS)), len(HEAT_COLORS) - 1)
    return HEAT_COLORS[idx]


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def display_treemap(
    console: Console,
    items: Sequence[SpaceItem],
    title: str = "Space Distribution",
    width: int = 70,
    height: int = 12,
) -> None:
    """
    Display a treemap-style heatmap visualization.

    Each item gets a rectangular block sized proportionally to its size.
    Colors indicate relative size (blue=small, red=large).

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

    # Calculate total cells and assign to items
    total_cells = width * height

    # Build cell assignments
    cells: list[tuple[SpaceItem, str, float]] = []  # (item, color, proportion)

    for item in sorted_items:
        proportion = item.size / total_size
        num_cells = max(1, int(proportion * total_cells))
        color = _get_heat_color(proportion)
        cells.extend([(item, color, proportion)] * num_cells)

    # Trim or pad to exact size
    if len(cells) > total_cells:
        cells = cells[:total_cells]
    elif len(cells) < total_cells:
        # Pad with the largest item
        if cells:
            cells.extend([cells[0]] * (total_cells - len(cells)))

    console.print()
    console.print(f"[bold]{title}[/] [dim]({format_size(total_size)} total)[/]")
    console.print()

    # Build the grid
    grid: list[list[tuple[SpaceItem, str, float]]] = []
    cell_idx = 0

    for row in range(height):
        grid_row = []
        for col in range(width):
            if cell_idx < len(cells):
                grid_row.append(cells[cell_idx])
                cell_idx += 1
            else:
                grid_row.append((sorted_items[0], HEAT_COLORS[0], 0))
        grid.append(grid_row)

    # Render the grid with labels
    # First pass: render the blocks
    for row_idx, row in enumerate(grid):
        line = Text()
        line.append("  ")  # Indent
        for item, color, _ in row:
            line.append(BLOCK, style=color)
        console.print(line)

    console.print()

    # Legend with top items
    max_legend = min(10, len(sorted_items))
    legend_items = sorted_items[:max_legend]

    # Two-column legend
    console.print(
        "  [bold]Legend:[/] [dim](color = relative size, blue→red = small→large)[/]"
    )
    console.print()

    for i in range(0, len(legend_items), 2):
        left_item = legend_items[i]
        left_prop = left_item.size / total_size
        left_color = _get_heat_color(left_prop)
        left_pct = left_prop * 100
        left_name = _truncate(left_item.name, 20)
        left_text = f"[{left_color}]{BLOCK}{BLOCK}[/] {left_name}: {format_size(left_item.size)} ({left_pct:.1f}%)"

        if i + 1 < len(legend_items):
            right_item = legend_items[i + 1]
            right_prop = right_item.size / total_size
            right_color = _get_heat_color(right_prop)
            right_pct = right_prop * 100
            right_name = _truncate(right_item.name, 20)
            right_text = f"[{right_color}]{BLOCK}{BLOCK}[/] {right_name}: {format_size(right_item.size)} ({right_pct:.1f}%)"
            console.print(f"  {left_text:<45} {right_text}")
        else:
            console.print(f"  {left_text}")

    # Show remaining count
    if len(sorted_items) > max_legend:
        remaining = len(sorted_items) - max_legend
        remaining_size = sum(item.size for item in sorted_items[max_legend:])
        console.print(
            f"\n  [dim]... and {remaining} more ({format_size(remaining_size)})[/]"
        )


def display_heatmap_bar(
    console: Console,
    items: Sequence[SpaceItem],
    title: str = "Space Distribution",
    width: int = 70,
) -> None:
    """
    Display a single-row heatmap bar with legend.

    Args:
        console: Rich console for output
        items: List of items with name and size
        title: Title for the display
        width: Width in characters
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

    console.print()
    console.print(f"[bold]{title}[/] [dim]({format_size(total_size)} total)[/]")
    console.print()

    # Build the bar
    bar = Text()
    bar.append("  ")

    items_in_bar: list[tuple[SpaceItem, str, int]] = []  # (item, color, width)
    remaining_width = width

    for item in sorted_items:
        proportion = item.size / total_size
        item_width = max(1, int(proportion * width)) if proportion > 0.005 else 0
        item_width = min(item_width, remaining_width)

        if item_width > 0:
            color = _get_heat_color(proportion)
            bar.append(BLOCK * item_width, style=color)
            items_in_bar.append((item, color, item_width))
            remaining_width -= item_width

        if remaining_width <= 0:
            break

    # Fill remainder with smallest shown item
    if remaining_width > 0 and items_in_bar:
        last_item, last_color, _ = items_in_bar[-1]
        bar.append(BLOCK * remaining_width, style=last_color)

    console.print(bar)
    console.print()

    # Legend
    max_legend = min(10, len(items_in_bar))

    for i in range(0, max_legend, 2):
        item, color, _ = items_in_bar[i]
        prop = item.size / total_size
        pct = prop * 100
        name = _truncate(item.name, 22)
        left = (
            f"[{color}]{BLOCK}{BLOCK}[/] {name}: {format_size(item.size)} ({pct:.1f}%)"
        )

        if i + 1 < max_legend:
            item2, color2, _ = items_in_bar[i + 1]
            prop2 = item2.size / total_size
            pct2 = prop2 * 100
            name2 = _truncate(item2.name, 22)
            right = f"[{color2}]{BLOCK}{BLOCK}[/] {name2}: {format_size(item2.size)} ({pct2:.1f}%)"
            console.print(f"  {left:<48} {right}")
        else:
            console.print(f"  {left}")

    if len(sorted_items) > max_legend:
        remaining = len(sorted_items) - max_legend
        remaining_size = sum(item.size for item in sorted_items[max_legend:])
        console.print(
            f"\n  [dim]... and {remaining} more ({format_size(remaining_size)})[/]"
        )
