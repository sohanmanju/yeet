"""Rich table displays for scan results."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from ..utils import (
    Project,
    ScanResults,
    CacheLocation,
    CacheScanResults,
    XcodeItem,
    XcodeItemType,
    XcodeScanResults,
    format_days_ago,
    format_size,
)


def display_scan_summary(console: Console, results: ScanResults) -> None:
    """Display a summary of the scan results."""
    console.print()

    stale_count = len(results.projects)
    total_size = sum(p.total_size for p in results.projects)

    console.print(
        Panel(
            f"[bold]Scan Complete[/]\n\n"
            f"  Projects scanned: [cyan]{results.total_projects_scanned:,}[/]\n"
            f"  Stale projects found: [yellow]{stale_count}[/]\n"
            f"  Total size (stale): [green]{format_size(total_size)}[/]",
            title="Scan Summary",
            border_style="green",
        )
    )

    if results.scan_errors:
        console.print(
            f"\n[dim]({len(results.scan_errors)} errors during scan - "
            f"some directories were inaccessible)[/]"
        )


def display_projects_table(
    console: Console,
    projects: list[Project],
    title: str = "Stale Projects",
    show_numbers: bool = True,
    max_display: int = 50,
    sort_by: str = "staleness",  # "staleness" or "size"
) -> None:
    """Display a table of projects."""
    if not projects:
        console.print(f"\n[dim]No {title.lower()} found.[/]")
        return

    # Sort projects
    if sort_by == "size":
        sorted_projects = sorted(projects, key=lambda p: p.total_size, reverse=True)
    else:  # staleness
        sorted_projects = sorted(projects, key=lambda p: p.days_stale, reverse=True)

    table = Table(
        title=f"{title} (showing {min(len(projects), max_display)} of {len(projects)})",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold",
    )

    if show_numbers:
        table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Project", style="cyan", no_wrap=True, max_width=25)
    table.add_column("Path", style="dim", no_wrap=True, max_width=35)
    table.add_column("Type", style="blue", justify="center", width=7)
    table.add_column("Size", style="green", justify="right", width=9)
    table.add_column("Last Opened", style="yellow", justify="right", width=13)
    table.add_column("Last Commit", style="magenta", justify="right", width=13)

    for i, project in enumerate(sorted_projects[:max_display]):
        row = []
        if show_numbers:
            row.append(str(i + 1))

        # Type label
        type_label = project.project_type.value

        # Last opened (most recent of access/modify)
        last_opened_days = min(project.days_since_accessed, project.days_since_modified)
        last_opened = format_days_ago(last_opened_days)

        # Last commit (or — if not git)
        if project.is_git_repo and project.days_since_commit is not None:
            last_commit = format_days_ago(project.days_since_commit)
        else:
            last_commit = "—"

        row.extend(
            [
                project.name,
                str(project.path.parent),
                type_label,
                project.size_formatted,
                last_opened,
                last_commit,
            ]
        )
        table.add_row(*row)

    console.print()
    console.print(table)

    if len(projects) > max_display:
        console.print(
            f"[dim]... and {len(projects) - max_display} more projects not shown.[/]"
        )

    # Show total size
    total_size = sum(p.total_size for p in projects)
    console.print(f"\n[bold]Total size:[/] [green]{format_size(total_size)}[/]")


def display_deletion_results(
    console: Console,
    deleted_projects: list[tuple[Project, bool, str]],
    use_trash: bool = False,
    dry_run: bool = False,
) -> None:
    """Display results of deletion operation."""
    console.print()

    projects_success = sum(1 for _, success, _ in deleted_projects if success)
    projects_failed = len(deleted_projects) - projects_success

    total_reclaimed = sum(p.total_size for p, success, _ in deleted_projects if success)

    title_action = "Dry Run" if dry_run else ("Moved to Trash" if use_trash else "Deletion")
    size_label = "Potential space reclaimed" if dry_run else "Space reclaimed"
    item_label = "would be moved to trash" if dry_run and use_trash else (
        "would be deleted" if dry_run else ("moved to trash" if use_trash else "deleted")
    )

    result_text = (
        f"[bold]{title_action} Complete[/]\n\n"
        f"  Projects {item_label}: [green]{projects_success}[/]"
        f"{f' ([red]{projects_failed} failed[/])' if projects_failed else ''}\n\n"
        f"  [bold green]{size_label}: {format_size(total_reclaimed)}[/]"
    )

    if use_trash and projects_success > 0 and not dry_run:
        result_text += (
            "\n\n[dim]Items moved to trash. You can restore them from "
            "your system trash if needed.[/]"
        )

    console.print(
        Panel(
            result_text,
            title=f"{title_action} Summary",
            border_style="green",
        )
    )

    # Show failures if any
    failures = [(item, msg) for item, success, msg in deleted_projects if not success]

    if failures:
        console.print("\n[bold red]Failed deletions:[/]")
        for project, msg in failures[:10]:
            console.print(f"  [red]Project:[/] {project.name} - {msg}")

        if len(failures) > 10:
            console.print(f"  [dim]... and {len(failures) - 10} more failures[/]")


def display_cache_scan_summary(console: Console, results: CacheScanResults) -> None:
    """Display a summary of the cache scan results."""
    console.print()

    # Group by category for summary
    by_category = results.by_category
    category_summary = []
    for category, caches in by_category.items():
        total = sum(c.size for c in caches)
        category_summary.append(
            f"  {category.value}: [cyan]{len(caches)}[/] ({format_size(total)})"
        )

    summary_text = (
        "\n".join(category_summary) if category_summary else "  No caches found"
    )

    console.print(
        Panel(
            f"[bold]Cache Scan Complete[/]\n\n"
            f"  Total caches found: [yellow]{len(results.caches)}[/]\n"
            f"  Total cache size: [green]{format_size(results.total_size)}[/]\n\n"
            f"[bold]By Category:[/]\n{summary_text}",
            title="Cache Summary",
            border_style="green",
        )
    )

    if results.scan_errors:
        console.print(
            f"\n[dim]({len(results.scan_errors)} errors during scan - "
            f"some directories were inaccessible)[/]"
        )


def display_cache_deletion_results(
    console: Console,
    deleted_caches: list[tuple[CacheLocation, bool, str]],
    use_trash: bool = False,
    dry_run: bool = False,
) -> None:
    """Display results of cache deletion operation."""
    console.print()

    caches_success = sum(1 for _, success, _ in deleted_caches if success)
    caches_failed = len(deleted_caches) - caches_success

    total_reclaimed = sum(c.size for c, success, _ in deleted_caches if success)

    title_action = "Dry Run" if dry_run else ("Moved to Trash" if use_trash else "Cache Cleanup")
    size_label = "Potential space reclaimed" if dry_run else "Space reclaimed"
    item_label = "would be moved to trash" if dry_run and use_trash else (
        "would be cleared" if dry_run else ("moved to trash" if use_trash else "cleared")
    )

    result_text = (
        f"[bold]{title_action} Complete[/]\n\n"
        f"  Caches {item_label}: [green]{caches_success}[/]"
        f"{f' ([red]{caches_failed} failed[/])' if caches_failed else ''}\n\n"
        f"  [bold green]{size_label}: {format_size(total_reclaimed)}[/]"
    )

    if use_trash and caches_success > 0 and not dry_run:
        result_text += (
            "\n\n[dim]Items moved to trash. You can restore them from "
            "your system trash if needed.[/]"
        )

    console.print(
        Panel(
            result_text,
            title="Cleanup Summary",
            border_style="green",
        )
    )

    # Show failures if any
    failures = [(item, msg) for item, success, msg in deleted_caches if not success]

    if failures:
        console.print("\n[bold red]Failed deletions:[/]")
        for cache, msg in failures[:10]:
            console.print(f"  [red]Cache:[/] {cache.name} - {msg}")

        if len(failures) > 10:
            console.print(f"  [dim]... and {len(failures) - 10} more failures[/]")


def display_xcode_scan_summary(console: Console, results: XcodeScanResults) -> None:
    """Display a summary of the Xcode scan results."""
    console.print()

    # Group by type for summary
    by_type = results.by_type
    type_summary = []
    for item_type in XcodeItemType:
        if item_type in by_type:
            items = by_type[item_type]
            total = sum(item.size for item in items)
            latest_count = sum(1 for item in items if item.is_latest)
            latest_info = f" ([cyan]{latest_count} latest[/])" if latest_count else ""
            type_summary.append(
                f"  {item_type.value}: [yellow]{len(items)}[/] ({format_size(total)}){latest_info}"
            )

    summary_text = "\n".join(type_summary) if type_summary else "  No Xcode items found"

    console.print(
        Panel(
            f"[bold]Xcode Scan Complete[/]\n\n"
            f"  Total items found: [yellow]{len(results.items)}[/]\n"
            f"  Total size: [green]{format_size(results.total_size)}[/]\n"
            f"  Reclaimable (excluding latest): [bold green]{format_size(results.reclaimable_size)}[/]\n\n"
            f"[bold]By Category:[/]\n{summary_text}",
            title="Xcode Cleanup Summary",
            border_style="cyan",
        )
    )

    if results.scan_errors:
        console.print(
            f"\n[dim]({len(results.scan_errors)} errors during scan - "
            f"some directories were inaccessible)[/]"
        )


def display_xcode_deletion_results(
    console: Console,
    deleted_items: list[tuple[XcodeItem, bool, str]],
    dry_run: bool = False,
) -> None:
    """Display results of Xcode cleanup operation."""
    console.print()

    items_success = sum(1 for _, success, _ in deleted_items if success)
    items_failed = len(deleted_items) - items_success

    total_reclaimed = sum(item.size for item, success, _ in deleted_items if success)

    console.print(
        Panel(
            f"[bold]{'Dry Run' if dry_run else 'Xcode Cleanup'} Complete[/]\n\n"
            f"  Items {'would be deleted' if dry_run else 'deleted'}: [green]{items_success}[/]"
            f"{f' ([red]{items_failed} failed[/])' if items_failed else ''}\n\n"
            f"  [bold green]{'Potential space reclaimed' if dry_run else 'Space reclaimed'}: {format_size(total_reclaimed)}[/]",
            title="Cleanup Summary",
            border_style="cyan",
        )
    )

    # Show failures if any
    failures = [(item, msg) for item, success, msg in deleted_items if not success]

    if failures:
        console.print("\n[bold red]Failed deletions:[/]")
        for item, msg in failures[:10]:
            console.print(f"  [red]{item.item_type.value}:[/] {item.name} - {msg}")

        if len(failures) > 10:
            console.print(f"  [dim]... and {len(failures) - 10} more failures[/]")
