"""Terminal-native dot meters inspired by fix-storage's storage visualization."""

from __future__ import annotations

from pathlib import Path
from shutil import disk_usage

from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.formatted_text import FormattedText

from ..formatting import format_size
from .application import TerminalApplication
from .geometry import content_width, fit, terminal_size
from .meter_canvas import BarModel, CanvasSegment
from .meter_pixels import graphics_supported

from .storage_model import Segment
from .theme import MUTED, PALETTE


def dot_meter(
    segments: list[Segment],
    total: int,
    *,
    width: int | None = None,
    rows: int = 7,
    focus: int | None = None,
    scanning: bool = False,
    context: str | None = None,
) -> FormattedText:
    """Render proportional segments; unassigned capacity stays unlit.

    Cell centers determine ownership so rounding never overflows the meter.
    Unknown/negative sizes don't become filled space.
    """
    width = content_width() if width is None else max(0, width)
    total = max(0, total)
    app = get_app_or_none()
    if (
        isinstance(app, TerminalApplication)
        and app.session.running
        and graphics_supported()
        and width > 0
        and terminal_size().rows >= 10
    ):
        budget = total
        model_segments = []
        for index, segment in enumerate(segments):
            size = min(budget, max(0, segment.size))
            budget -= size
            fraction = size / total if total > 0 and segment.color != MUTED else 0
            color = tuple(int(segment.color[i : i + 2], 16) for i in (1, 3, 5))
            model_segments.append(
                CanvasSegment(segment.id or str(index), color, fraction)
            )
        model = BarModel(
            tuple(model_segments),
            (segments[focus].id or str(focus)) if focus is not None else None,
            scanning,
        )
        return app.session.meter(model, width, context)
    boundaries = []
    used = 0
    for segment in segments:
        used += max(0, segment.size)
        boundaries.append((min(used, total), segment.color))
    lines = []
    for row in range(min(rows, max(1, terminal_size().rows // 6))):
        lines.append(("", "  "))
        for column in range(width):
            point = (column + 0.5) * total / width
            color = next(
                (color for end, color in boundaries if total and point < end), MUTED
            )
            highlight = color != MUTED and (column * 17 + row * 31) % 23 == 0
            lines.append(
                (
                    f"fg:{'#e6e6e6' if highlight else color}",
                    "•" if color != MUTED else "·",
                )
            )
        lines.append(("", "\n"))
    return FormattedText(lines)


def legend(
    segments: list[Segment], *, width: int | None = None, focus: int | None = None
) -> FormattedText:
    width = content_width() if width is None else width
    lines = [("", "  ")]
    used = 0
    if terminal_size().rows < 20 and len(segments) > 1:
        index = focus if focus is not None else 0
        segment = segments[index]
        label = fit(
            f"{segment.label} {format_size(segment.size)} · +{len(segments) - 1} groups",
            max(1, width - 2),
        ).rstrip()
        return FormattedText(
            [(f"fg:{segment.color}", "  ● "), ("class:help", label + "\n")]
        )
    for segment in segments:
        label = f"{segment.label} {format_size(max(0, segment.size))}"
        label = fit(label, max(1, width - 3)).rstrip()
        length = len(label) + 3
        if used and used + length > width:
            lines.append(("", "\n  "))
            used = 0
        lines.extend([(f"fg:{segment.color}", "● "), ("class:help", label + " ")])
        used += length
    lines.append(("", "\n"))
    return FormattedText(lines)


def disk_overview(path: Path) -> FormattedText:
    """Read filesystem capacity only; never walk the disk for the menu."""
    try:
        usage = disk_usage(path)
    except OSError:
        return FormattedText([("class:help", "  Disk capacity unavailable\n")])
    segments = [Segment("Used", usage.used, PALETTE[0])]
    percent = round(usage.used / usage.total * 100) if usage.total else 0
    lines = [
        ("class:footer", f"  {format_size(usage.free)}"),
        ("class:help", " free"),
        ("class:dim", "  ·  "),
        ("class:normal", f"{format_size(usage.used)}"),
        ("class:help", f" used of {format_size(usage.total)}  ·  {percent}% full\n"),
    ]
    lines.extend(dot_meter(segments, usage.total))
    return FormattedText(lines)


class ScanBreakdown:
    """Measured inventory, independent of cursor and deletion checkboxes.

    Like fix-storage's barModel, widths come only from measured bytes; the
    current group changes brightness. The denominator here is explicitly the
    scan results, because cleanup scans do not inventory the whole disk.
    """

    def __init__(self, entries: list[tuple[str, int]]) -> None:
        sizes: dict[str, int] = {}
        for group, size in entries:
            sizes[group] = sizes.get(group, 0) + max(0, size)
        ranked = sorted(sizes.items(), key=lambda pair: (-pair[1], pair[0]))
        self.total = sum(sizes.values())
        displayed = (
            ranked if len(ranked) <= len(PALETTE) else ranked[: len(PALETTE) - 1]
        )
        self.segments = [
            Segment(group, size, PALETTE[i])
            for i, (group, size) in enumerate(displayed)
        ]
        self.group_indices = {group: i for i, (group, _) in enumerate(displayed)}
        if len(displayed) < len(ranked):
            index = len(self.segments)
            remaining = ranked[len(displayed) :]
            self.segments.append(
                Segment(
                    f"Other ({len(remaining)} groups)",
                    sum(size for _, size in remaining),
                    PALETTE[index],
                )
            )
            self.group_indices.update({group: index for group, _ in remaining})

    def color_for(self, group: str) -> str:
        index = self.group_indices.get(group)
        return self.segments[index].color if index is not None else MUTED

    def render(self, focused_group: str | None = None) -> FormattedText:
        lines = [
            ("class:help", f"  Scan results · {format_size(self.total)} measured\n")
        ]
        lines.extend(
            dot_meter(
                self.segments,
                self.total,
                focus=self.group_indices.get(focused_group),
                context="scan-results",
            )
        )
        lines.extend(legend(self.segments, focus=self.group_indices.get(focused_group)))
        lines.append(("", "\n"))
        return FormattedText(lines)
