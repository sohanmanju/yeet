"""Rendering helpers for the disk explorer UI."""

from __future__ import annotations

from pathlib import Path
from shutil import get_terminal_size

from prompt_toolkit.formatted_text import FormattedText

from ..utils import DiskItem, SIZE_LOADING, format_days_ago, format_size


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
            crumbs.append(("class:breadcrumb", part))
    else:
        for i, part in enumerate(parts):
            if i > 0:
                crumbs.append(("class:breadcrumb-sep", separator))
            display = part if part != "/" else "/"
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
    lines.append(("class:info-value", str(item.path)))
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

    if item.is_dir:
        if item.item_count is not None:
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
    w = ui.col_widths
    header = (
        f"{'':>{w['select']}} "
        f"{'':>{w['icon']}}"
        f"{'Name':<{w['name']}} "
        f"{'Size':>{w['size']}} "
        f"{'Modified':>{w['modified']}}"
    )
    return FormattedText([("class:header", header)])


def get_row(ui, idx: int, display_items: list[DiskItem]) -> FormattedText:
    item = display_items[idx]
    w = ui.col_widths

    is_selected = item.path in ui.selected
    is_cursor = idx == ui.cursor

    select_char = "[x]" if is_selected else "[ ]"
    icon = "▸ " if item.is_dir else "  "

    name = item.name
    if len(name) > w["name"] - 2:
        name = name[: w["name"] - 5] + "..."

    row = (
        f"{select_char:>{w['select']}} "
        f"{icon}{name:<{w['name']}} "
        f"{item.size_formatted:>{w['size']}} "
        f"{format_days_ago(item.days_since_modified):>{w['modified']}}"
    )

    if is_cursor and is_selected:
        style = "class:cursor-selected"
    elif is_cursor:
        style = "class:cursor"
    elif is_selected:
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

        size = item.size if item.size > 0 else 0
        if ext in stats:
            count, total = stats[ext]
            stats[ext] = (count + 1, total + size)
        else:
            stats[ext] = (1, size)

    result = [(ext, count, size) for ext, (count, size) in stats.items()]
    result.sort(key=lambda x: x[2], reverse=True)
    return result


def get_extensions_content(ui) -> FormattedText:
    lines: list[tuple[str, str]] = []
    stats = calculate_extension_stats(ui)

    total_size = sum(size for _, _, size in stats)
    total_count = sum(count for _, count, _ in stats)

    path_str = str(ui.current_path)
    home = str(Path.home())
    if path_str.startswith(home):
        path_str = "~" + path_str[len(home) :]

    max_path_len = 40
    if len(path_str) > max_path_len:
        path_str = "..." + path_str[-(max_path_len - 3) :]

    box_width = 60
    title = f" File Types in {path_str} "
    padding = box_width - len(title) - 2
    left_pad = padding // 2
    right_pad = padding - left_pad
    lines.append(("", "\n\n"))
    lines.append(
        ("class:overlay-border", f"  ╭{'─' * left_pad}{title}{'─' * right_pad}╮\n")
    )
    lines.append(("class:overlay-border", f"  │{' ' * (box_width - 2)}│\n"))

    header = "  Extension       Count        Size       % of Total"
    lines.append(("class:overlay-border", "  │"))
    lines.append(("class:overlay-header", f"{header:<{box_width - 4}}"))
    lines.append(("class:overlay-border", "│\n"))
    lines.append(("class:overlay-border", f"  │{'─' * (box_width - 2)}│\n"))

    threshold = total_size * 0.001 if total_size > 0 else 0
    max_extensions = 15
    other_count = 0
    other_size = 0
    displayed = 0

    for ext, count, size in stats:
        if displayed >= max_extensions or (size < threshold and displayed > 0):
            other_count += count
            other_size += size
        else:
            percent = (size / total_size * 100) if total_size > 0 else 0
            size_str = format_size(size)
            row = f"  {ext:<14} {count:>6}   {size_str:>10}       {percent:>5.1f}%"
            lines.append(("class:overlay-border", "  │"))
            lines.append(("class:overlay-row", f"{row:<{box_width - 4}}"))
            lines.append(("class:overlay-border", "│\n"))
            displayed += 1

    if other_count > 0:
        percent = (other_size / total_size * 100) if total_size > 0 else 0
        size_str = format_size(other_size)
        row = f"  {'(other)':<14} {other_count:>6}   {size_str:>10}       {percent:>5.1f}%"
        lines.append(("class:overlay-border", "  │"))
        lines.append(("class:overlay-row-dim", f"{row:<{box_width - 4}}"))
        lines.append(("class:overlay-border", "│\n"))

    lines.append(("class:overlay-border", f"  │{'─' * (box_width - 2)}│\n"))
    total_size_str = format_size(total_size)
    total_row = f"  {'Total':<14} {total_count:>6}   {total_size_str:>10}       100.0%"
    lines.append(("class:overlay-border", "  │"))
    lines.append(("class:overlay-total", f"{total_row:<{box_width - 4}}"))
    lines.append(("class:overlay-border", "│\n"))
    lines.append(("class:overlay-border", f"  │{' ' * (box_width - 2)}│\n"))
    lines.append(("class:overlay-border", f"  ╰{'─' * (box_width - 2)}╯\n"))
    lines.append(
        ("class:overlay-help", "                   Press 'e' or Esc to close\n")
    )

    return FormattedText(lines)


def get_help_content(ui) -> FormattedText:
    lines: list[tuple[str, str]] = []
    help_text = [
        "",
        "╭─────────────────── Keyboard Shortcuts ───────────────────╮",
        "│                                                          │",
        "│  Navigation                                              │",
        "│    ↑/k        Move up                                    │",
        "│    ↓/j        Move down                                  │",
        "│    Enter/l    Open directory                             │",
        "│    h/Backspace Go to parent                              │",
        "│    g          Go to top                                  │",
        "│    G          Go to bottom                               │",
        "│    Ctrl+U     Page up                                    │",
        "│    Ctrl+D     Page down                                  │",
        "│    ~          Go to home directory                       │",
        "│    /          Go to root                                 │",
        "│                                                          │",
        "│  Selection                                               │",
        "│    Space      Toggle selection                           │",
        "│    *          Select all visible                         │",
        "│    u          Deselect all                               │",
        "│                                                          │",
        "│  Filtering                                               │",
        "│    f          Filter by name                             │",
        "│    a          Filter by age (days old)                   │",
        "│    c          Clear name filter                          │",
        "│    A          Clear age filter                           │",
        "│                                                          │",
        "│  Actions                                                 │",
        "│    d          Delete selected                            │",
        "│    v          View selection                             │",
        "│    o          Open in Finder                             │",
        "│    i          Show item info                             │",
        "│    r          Refresh                                    │",
        "│    b          Next bookmark                              │",
        "│    B          Add current to bookmarks                   │",
        "│                                                          │",
        "│  Display                                                 │",
        "│    s          Cycle sort mode                            │",
        "│    t          Toggle small items                         │",
        "│    ?          Show/hide this help                        │",
        "│    q/Esc      Quit                                       │",
        "│                                                          │",
        "╰──────────────────────────────────────────────────────────╯",
        "",
        "                    Press any key to close",
        "",
    ]

    for line in help_text:
        lines.append(("class:help-box", f"  {line}\n"))

    return FormattedText(lines)


def get_content(ui) -> FormattedText:
    if ui.show_help:
        return get_help_content(ui)
    if ui.show_extensions:
        return get_extensions_content(ui)

    lines: list[tuple[str, str]] = []
    display_items = ui._get_display_items()

    cached_size = ui.explorer.get_cached_size(ui.current_path)
    if cached_size is not None:
        size_str = format_size(cached_size)
    else:
        known_size = sum(item.size for item in ui.items if item.size > 0)
        size_str = f"~{format_size(known_size)}" if known_size > 0 else "..."

    lines.append(("", "\n  "))
    lines.extend(get_breadcrumbs(ui))
    lines.append(("class:path-size", f" ({size_str})"))
    lines.append(("", "\n\n"))

    lines.append(
        (
            "class:help",
            "  [j/k] Navigate  [g/G] Top/Bottom  [Ctrl+U/D] Page  [Enter] Open  [h] Back  [?] Help\n",
        )
    )
    lines.append(
        (
            "class:help",
            "  [Space] Select  [*] All  [u] None  [d] Delete  [v] View  [f] Filter  [e] Types  [?] Help  [q] Quit\n",
        )
    )

    if not ui.show_small_items:
        threshold = format_size(ui.explorer.min_size_bytes)
        lines.append(
            ("class:hint", f"  Hiding items < {threshold}. Press [t] to show all.\n")
        )

    lines.append(("", "\n"))
    lines.append(("class:header", "  "))
    lines.extend(get_header(ui))
    lines.append(("", "\n"))
    lines.append(("class:header", "  " + "─" * 95 + "\n"))

    if not display_items:
        if ui.filtered_items is not None:
            lines.append(("class:dim", "  (no items match filter)\n"))
        else:
            lines.append(("class:dim", "  (empty or no items above size threshold)\n"))
    else:
        term_height = get_terminal_size().lines
        reserved_lines = 16 if not ui.show_info_panel else 22
        viewport_size = max(5, term_height - reserved_lines)

        total = len(display_items)
        if total <= viewport_size:
            start, end = 0, total
        else:
            half_viewport = viewport_size // 2
            start = max(0, ui.cursor - half_viewport)
            end = min(total, start + viewport_size)
            if end - start < viewport_size:
                start = max(0, end - viewport_size)

        if start > 0:
            lines.append(("class:dim", f"  ... {start} more items above ...\n"))

        for idx in range(start, end):
            lines.append(("", "  "))
            lines.extend(get_row(ui, idx, display_items))
            lines.append(("", "\n"))

        if end < total:
            lines.append(("class:dim", f"  ... {total - end} more items below ...\n"))

    lines.append(("", "\n"))
    lines.append(("class:header", "  " + "─" * 95 + "\n"))

    if ui.show_info_panel and display_items and ui.cursor < len(display_items):
        item = display_items[ui.cursor]
        lines.append(("class:info-header", "  Item Info:\n"))
        lines.extend(get_item_info(ui, item))
        lines.append(("class:header", "  " + "─" * 95 + "\n"))

    if ui.age_filter_mode:
        lines.append(
            (
                "class:filter-input",
                f"  Show items older than (days): {ui.age_filter_input}_\n",
            )
        )
    elif ui.filter_mode:
        lines.append(("class:filter-input", f"  Filter: {ui.filter_text}_\n"))
    elif ui.filtered_items is not None or ui.age_filter_days is not None:
        filter_parts = []
        if ui.filter_text:
            filter_parts.append(f'Name: "{ui.filter_text}"')
        if ui.age_filter_days is not None:
            filter_parts.append(f"Age: >{ui.age_filter_days} days")
        filter_str = " | ".join(filter_parts)
        lines.append(
            (
                "class:filter-active",
                f"  {filter_str} ({len(ui.filtered_items) if ui.filtered_items else len(ui.items)} of {len(ui.items)})  │  [c] Clear name  [A] Clear age\n",
            )
        )

    if ui.age_filter_days is not None and not ui.age_filter_mode and not ui.filter_mode:
        lines.append(
            (
                "class:hint",
                f"  Showing items older than {ui.age_filter_days} days | [A] Clear age filter\n",
            )
        )

    total_selected_size = sum(ui.explorer.get_cached_size(p) or 0 for p in ui.selected)
    if ui.selected:
        lines.append(
            (
                "class:selection-summary",
                f"  Selected: {len(ui.selected)} items ({format_size(total_selected_size)}) | Press [d] to delete, [v] to view\n",
            )
        )
    else:
        lines.append(
            (
                "class:selection-hint",
                "  Selected: 0 items | Press [Space] to select items\n",
            )
        )

    if ui.bookmarks:
        bookmark_names = ", ".join(
            path.name if path.name else "/" for path in ui.bookmarks[:4]
        )
        more = f" +{len(ui.bookmarks) - 4} more" if len(ui.bookmarks) > 4 else ""
        lines.append(
            (
                "class:bookmark-hint",
                f"  Bookmarks: {bookmark_names}{more} | [b] Next [B] Add current\n",
            )
        )

    if ui.status_message:
        lines.append(("class:status", f"  {ui.status_message}\n"))

    sort_label = {"size": "Size", "name": "Name", "modified": "Modified"}[ui.sort_mode]
    lines.append(("class:dim", f"  Sort: {sort_label} | [r] Refresh\n"))

    return FormattedText(lines)


def show_selection_view(ui) -> None:
    ui.status_message = f"Selection: {len(ui.selected)} items - press [d] to delete"
