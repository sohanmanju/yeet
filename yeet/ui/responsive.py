"""Adaptive table columns; terminal windows own clipping and scrolling."""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import content_width, fit


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    width: int
    align: str = "left"
    priority: int = (
        0  # Required columns have priority 0; optional columns rank higher first.
    )
    grow: int = 0


@dataclass(frozen=True)
class TableSchema:
    columns: tuple[Column, ...]
    marker_width: int = 0


def table_columns(schema: TableSchema) -> list[tuple[Column, int]]:
    spec = schema.columns
    available = max(1, content_width() - schema.marker_width)
    chosen = [column for column in spec if not column.priority]
    used = sum(column.width for column in chosen) + len(chosen) - 1
    for column in sorted((c for c in spec if c.priority), key=lambda c: -c.priority):
        if used + column.width + 1 <= available:
            chosen.append(column)
            used += column.width + 1
    columns = [(column, column.width) for column in spec if column in chosen]
    extra = available - used
    # Very narrow windows keep the checkbox and size until there is no room left.
    if extra < 0:
        columns = [
            (column, max(1, width + extra) if column.key == "name" else width)
            for column, width in columns
        ]
    else:
        weight = sum(column.grow for column, _ in columns)
        remaining = extra
        grown = []
        for column, width in columns:
            addition = extra * column.grow // weight if weight else 0
            remaining -= addition
            grown.append((column, width + addition))
        columns = [
            (column, width + remaining if column.key == "name" else width)
            for column, width in grown
        ]
    return columns


def table_line(schema: TableSchema, values: dict[str, str] | None = None) -> str:
    result = " ".join(
        fit(
            column.label if values is None else values.get(column.key, ""),
            width,
            align=column.align,
        )
        for column, width in table_columns(schema)
    )
    return fit(result, max(1, content_width() - schema.marker_width))
