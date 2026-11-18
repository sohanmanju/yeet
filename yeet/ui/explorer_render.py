"""Rendering helpers for the disk explorer UI."""

from __future__ import annotations

from prompt_toolkit.formatted_text import FormattedText

from ..utils import SIZE_LOADING, DiskItem, format_days_ago, format_size
from .geometry import content_width, single_line
from .meter import MUTED, PALETTE, Segment, dot_meter, legend
from .responsive import table_line
from .table_schemas import EXPLORER, EXTENSIONS
from .view import ScreenView


def get_breadcrumbs(ui, max_width: int = 70) -> FormattedText:
    """Generate breadcrumb navigation for the current path."""
    parts = ui.current_path.parts
    if not parts:
        return FormattedText([("class:breadcrumb", "/")])

    crumbs: list[tuple[str, str]] = []
    separator = " > "
    full_path = separator.join(parts)

    if len(full_path) > max_width and len(parts) > 3:
        crumbs.append(("class:breadcrumb", parts[0] if parts[0] != "/" else "/"))
        crumbs.append(("class:breadcrumb-sep", separator))
        crumbs.append(("class:breadcrumb-dim", "..."))
        crumbs.append(("class:breadcrumb-sep", separator))
        for i, part in enumerate(parts[-2:]):
            if i > 0:
                crumbs.append(("class:breadcrumb-sep", separator))
            crumbs.append(("class:breadcrumb", single_line(part)))
    else:
        for i, part in enumerate(parts):
            if i > 0:
                crumbs.append(("class:breadcrumb-sep", separator))
            display = single_line(part)
            if i == len(parts) - 1:
                crumbs.append(("class:breadcrumb-current", display))
            else:
                crumbs.append(("class:breadcrumb", display))

    return FormattedText(crumbs)


def get_parent_total_size(ui) -> int | None:
    total = 0
    for item in ui.items:
        if item.size > 0 and item.size != SIZE_LOADING:
            total += item.size
    return total if total > 0 else None


def get_item_info(ui, item: DiskItem) -> FormattedText:
    lines: list[tuple[str, str]] = []

    lines.append(("class:info-label", "  Path: "))
    lines.append(("class:info-value", single_line(str(item.path))))
    lines.append(("", "\n"))

    lines.append(("class:info-label", "  Size: "))
    lines.append(("class:info-value", item.size_formatted))

    parent_size = get_parent_total_size(ui)
    if parent_size and item.size > 0 and item.size != SIZE_LOADING:
        pct = (item.size / parent_size) * 100
        lines.append(("class:info-value", f" ({pct:.1f}% of parent)"))
    lines.append(("", "\n"))

    lines.append(("class:info-label", "  Type: "))
    lines.append(("class:info-value", "Directory" if item.is_dir else "File"))
    lines.append(("", "\n"))

    if item.is_dir and item.item_count is not None:
        lines.append(("class:info-label", "  Items: "))
        lines.append(("class:info-value", str(item.item_count)))
        lines.append(("", "\n"))

    lines.append(("class:info-label", "  Modified: "))
    try:
        lines.append(("class:info-value", item.modified.strftime("%Y-%m-%d %H:%M:%S")))
        lines.append(
            ("class:info-dim", f" ({format_days_ago(item.days_since_modified)})")
        )
    except (OSError, ValueError, AttributeError):
        lines.append(("class:info-value", "Unknown"))
    lines.append(("", "\n"))

    return FormattedText(lines)


def get_header(ui) -> FormattedText:
    return FormattedText([("class:header", table_line(EXPLORER))])


def get_row(ui, idx: int, display_items: list[DiskItem]) -> FormattedText:
    item = display_items[idx]
    selected, cursor = item.path in ui.selected, idx == ui.cursor
    total = get_parent_total_size(ui) or 0
    fraction = min(1, max(0, item.size) / total) if total else 0
    lit = round(fraction * 8)
    row = table_line(
        EXPLORER,
        {
            "select": "[x]" if selected else "[ ]",
            "name": ("▸ " if item.is_dir else "  ") + item.name,
            "size": item.size_formatted,
            "modified": format_days_ago(item.days_since_modified),
            "share": "⠿" * lit + "⠂" * (8 - lit),
        },
    )
    if cursor and selected:
        style = "class:cursor-selected"
    elif cursor:
        style = "class:cursor"
    elif selected:
        style = "class:selected"
    elif item.is_loading:
        style = "class:loading"
    else:
        style = "class:normal"
    return FormattedText([(style, row)])


def calculate_extension_stats(ui) -> list[tuple[str, int, int]]:
    stats: dict[str, tuple[int, int]] = {}

    for item in ui.items:
        if item.is_dir:
            ext = "(directories)"
        else:
            suffix = item.path.suffix.lower()
            ext = suffix if suffix else "(no extension)"

        size = max(0, item.size)
        if ext in stats:
            count, total = stats[ext]
            stats[ext] = (count + 1, total + size)
        else:
            stats[ext] = (1, size)

    result = [(ext, count, size) for ext, (count, size) in stats.items()]
    result.sort(key=lambda x: x[2], reverse=True)
    return result


HELP_ROWS = [
    "↑/k, ↓/j        Move between items",
    "Enter/l         Open directory",
    "h/Backspace     Parent directory",
    "g / G           Top / bottom",
    "Ctrl+U/D        Page up / down",
    "~ / /           Home / root",
    "Space           Toggle selection",
    "* / u           Select all / none",
    "f / c           Name filter / clear",
    "a / A           Age filter / clear",
    "d               Delete selected",
    "v               View selection",
    "o               Reveal item",
    "i               Toggle item info",
    "r               Refresh directory",
    "b / B           Next / add bookmark",
    "s / t           Sort / small items",
    "e               File type breakdown",
    "? / Esc         Close help",
    "q               Quit explorer",
]


def overlay_length(ui) -> int:
    return len(HELP_ROWS) if ui.show_help else len(calculate_extension_stats(ui))


def get_extensions_content(ui) -> ScreenView:
    stats = calculate_extension_stats(ui)
    total_size = sum(size for _, _, size in stats)
    total_count = sum(count for _, count, _ in stats)
    header = [
        ("class:title", f"  File types · {single_line(str(ui.current_path))}\n"),
        ("class:header", "  " + table_line(EXTENSIONS) + "\n"),
    ]
    footer = [
        (
            "class:overlay-total",
            f"  Total: {total_count} items · {format_size(total_size)}\n",
        ),
        ("class:overlay-help", "  ↑/↓ scroll · e/Esc close\n"),
    ]

    def row(index):
        extension, count, size = stats[index]
        values = {
            "name": extension,
            "count": str(count),
            "size": format_size(size),
            "percent": f"{size / total_size * 100:.1f}%" if total_size else "0%",
        }
        return FormattedText(
            [("class:overlay-row", "  " + table_line(EXTENSIONS, values))]
        )

    return ScreenView(
        FormattedText(header), len(stats), row, FormattedText(footer), ui.overlay_cursor
    )


def get_help_content(ui) -> ScreenView:
    return ScreenView(
        FormattedText([("class:title", "  Keyboard shortcuts\n")]),
        len(HELP_ROWS),
        lambda index: FormattedText([("class:help-box", "  " + HELP_ROWS[index])]),
        FormattedText([("class:overlay-help", "  ↑/↓ scroll · ?/Esc close\n")]),
        ui.overlay_cursor,
    )


def get_storage_overview(ui) -> FormattedText:
    """Show measured children, retaining unmeasured space while sizes load."""
    known = sorted(
        (item for item in ui.items if item.size > 0),
        key=lambda item: (-item.size, str(item.path)),
    )
    measured = sum(item.size for item in known)
    cached = ui.explorer.get_cached_size(ui.current_path)
    total = max(measured, cached or 0)
    segments = [
        Segment(item.name, item.size, PALETTE[index])
        for index, item in enumerate(known[:5])
    ]
    other = sum(item.size for item in known[5:])
    if other:
        segments.append(Segment("Other", other, PALETTE[5]))
    if total > measured:
        segments.append(Segment("Unmeasured", total - measured, MUTED))
    loading = sum(item.is_loading for item in ui.items)
    status = (
        f"Measuring {loading} {'folder' if loading == 1 else 'folders'}"
        if loading
        else "Measured children"
    )
    lines = [("class:help", f"  {status} · {format_size(measured)}\n")]
    visible = ui._get_display_items()
    current = visible[ui.cursor] if visible and ui.cursor < len(visible) else None
    focus = next(
        (
            i
            for i, item in enumerate(known[:5])
            if current and item.path == current.path
        ),
        None,
    )
    lines.extend(
        dot_meter(
            segments,
            total,
            focus=focus if not loading else None,
            scanning=bool(loading),
            context=str(ui.current_path),
        )
    )
    if segments:
        lines.extend(legend(segments, focus=focus))
    else:
        lines.append(
            ("class:help", "  Waiting for sizes" if loading else "  No measured items")
        )
        lines.append(("", "\n"))
    return FormattedText(lines)


def get_content(ui) -> ScreenView:
    if ui.show_help:
        return get_help_content(ui)
    if ui.show_extensions:
        return get_extensions_content(ui)
    items = ui._get_display_items()
    cached = ui.explorer.get_cached_size(ui.current_path)
    measured = sum(max(0, item.size) for item in ui.items)
    size = format_size(cached) if cached is not None else "~" + format_size(measured)
    header = [
        ("", "  "),
        *get_breadcrumbs(ui, max_width=max(10, content_width() - len(size) - 3)),
        ("class:path-size", f" ({size})\n"),
    ]
    header.extend(get_storage_overview(ui))
    header.extend(
        [
            ("", "  "),
            *get_header(ui),
            ("", "\n"),
            ("class:header", "  " + "─" * content_width() + "\n"),
        ]
    )
    footer = []
    if ui.age_filter_mode:
        footer.append(
            ("class:filter-input", f"  Older than (days): {ui.age_filter_input}_\n")
        )
    elif ui.filter_mode:
        footer.append(("class:filter-input", f"  Filter: {ui.filter_text}_\n"))
    selected_size = sum(ui.explorer.get_cached_size(path) or 0 for path in ui.selected)
    footer.append(
        (
            "class:selection-summary" if ui.selected else "class:selection-hint",
            f"  Selected: {len(ui.selected)} items ({format_size(selected_size)})\n",
        )
    )
    hints = (
        "q quit · Enter open · Space select"
        if content_width() < 65
        else "j/k move · Enter open · h back · Space select · d delete · ? help · q quit"
    )
    footer.append(("class:help", "  " + hints + "\n"))
    if ui.status_message:
        footer.append(("class:status", f"  {single_line(ui.status_message)}\n"))
    if ui.filtered_items is not None or ui.age_filter_days is not None:
        filters = []
        if ui.filter_text:
            filters.append(f'Name: "{ui.filter_text}"')
        if ui.age_filter_days is not None:
            filters.append(f"Age: >{ui.age_filter_days} days")
        footer.append(
            ("class:filter-active", "  " + " · ".join(filters) + " · c/A clear\n")
        )
    if ui.show_info_panel and items:
        footer.append(("class:info-header", "  Item info\n"))
        footer.extend(get_item_info(ui, items[min(ui.cursor, len(items) - 1)]))
    if not ui.show_small_items:
        footer.append(
            (
                "class:hint",
                f"  Hiding < {format_size(ui.explorer.min_size_bytes)} · t show all\n",
            )
        )
    if ui.bookmarks:
        names = ", ".join(path.name or "/" for path in ui.bookmarks[:4])
        footer.append(("class:bookmark-hint", f"  Bookmarks: {names} · b next\n"))
    footer.append(
        ("class:dim", f"  Sort: {ui.sort_mode} · s change · r refresh · ? help\n")
    )

    def row(index):
        if not items:
            message = (
                "No items match filter"
                if ui.filtered_items is not None
                else "No visible items"
            )
            return FormattedText([("class:dim", "  " + message)])
        return FormattedText([("", "  "), *get_row(ui, index, items)])

    return ScreenView(
        FormattedText(header), max(1, len(items)), row, FormattedText(footer), ui.cursor
    )


def show_selection_view(ui) -> None:
    ui.status_message = f"Selection: {len(ui.selected)} items - press [d] to delete"
