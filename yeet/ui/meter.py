"""Terminal-native dot meters inspired by fix-storage's storage visualization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import disk_usage

from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.formatted_text import FormattedText

from ..utils import DiskItem, LeftoverItem, PurgeArtifact, SelectableItem, format_size
from .application import TerminalApplication
from .geometry import content_width, fit, terminal_size
from .meter_canvas import BarModel, CanvasSegment
from .meter_pixels import graphics_supported

PALETTE = ("#3b82f6", "#22c55e", "#22d3ee", "#8b5cf6", "#ec4899", "#eab308")
MUTED = "#525252"
GREEN = "#4ade80"

# Applied after each screen's semantic styles to keep all interactive views cohesive.
THEME = {
    "brand": "bold #22d3ee",
    "key": "#e6e6e6",
    "dim": "#666666",
    "detail": "#a3a3a3",
    "status": "#22d3ee",
    "menu-description": "#8c8c8c",
    "menu-description-focus": "bg:#262626 #b5b5b5",
    "section-header": "#8c8c8c",
    "selection-hint": "#8c8c8c",
    "breadcrumb": "#8c8c8c",
    "breadcrumb-sep": "#525252",
    "info-label": "#8c8c8c",
    "info-value": "#d4d4d4",
    "title": "bold #e6e6e6",
    "header": "#8c8c8c",
    "help": "#8c8c8c",
    "normal": "#d4d4d4",
    "selected": GREEN,
    "cursor": "bg:#262626 #ffffff",
    "cursor-selected": f"bg:#173326 {GREEN}",
    "footer": "bold #e6e6e6",
    "selection-summary": f"bold {GREEN}",
    "breadcrumb-current": "bold #e6e6e6",
    "path-size": "#8c8c8c",
}


@dataclass(frozen=True)
class Segment:
    label: str
    size: int
    color: str
    id: str | None = None


def meter_width() -> int:
    return content_width()


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
    width = meter_width() if width is None else max(0, width)
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
            # Stable highlights give the dots texture without a redraw timer.
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
    width = meter_width() if width is None else width
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


_FILE_GROUPS = {
    "Photos": ".jpg .jpeg .png .gif .webp .heic .heif .raw .cr2 .nef .tiff .tif .svg .avif .psd",
    "Videos": ".mp4 .mov .mkv .avi .webm .m4v .mpg .mpeg .wmv",
    "Music": ".mp3 .m4a .wav .flac .aac .ogg .aiff .alac",
    "Archives": ".zip .tar .gz .bz2 .xz .7z .rar .zst .tgz",
    "Installers": ".dmg .pkg .iso .img .msi",
    "Apps": ".app .exe .apk .ipa .appimage",
    "Developer": ".py .pyc .js .ts .tsx .jsx .rs .go .java .class .jar .o .a .so .dylib .wasm .sqlite .db",
    "Documents": ".pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .csv .epub .pages .numbers .key",
}
_EXTENSION_GROUP = {
    extension: group
    for group, extensions in _FILE_GROUPS.items()
    for extension in extensions.split()
}


def file_storage_group(item: SelectableItem | LeftoverItem | DiskItem) -> str:
    """Use supplied app/project ownership, then file type; never guess an app."""
    if isinstance(item, LeftoverItem) and item.app_hint:
        return item.app_hint
    for part in item.path.parts:
        if part.lower().endswith(".app"):
            return part[:-4]
    if isinstance(item, PurgeArtifact):
        return item.project_name
    return _EXTENSION_GROUP.get(item.path.suffix.lower(), "Other files")
