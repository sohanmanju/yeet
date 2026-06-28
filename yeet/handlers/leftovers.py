"""Handler for leftover app data cleanup workflow."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel

from ..config import get_config
from ..json_output import dump_json, leftovers_scan_payload
from ..scanner import LeftoverScanner
from ..utils import format_size, is_macos
from ..ui.selector import select_files_interactive

from .common import (
    get_progress_context,
    check_trash_availability,
    record_history,
)
from .files import (
    confirm_file_deletion,
    display_file_deletion_results,
    perform_file_deletions,
)


def _display_leftovers_summary(console: Console, results) -> None:
    console.print()

    by_source = results.by_source
    source_lines = []
    source_totals = {
        source: sum(item.size for item in items) for source, items in by_source.items()
    }
    for source, total in sorted(source_totals.items(), key=lambda item: item[1], reverse=True):
        items = by_source[source]
        source_lines.append(f"  {source}: {len(items)} leftovers ({format_size(total)})")

    summary_text = "\n".join(source_lines) if source_lines else "  No leftovers found"

    console.print(
        Panel(
            f"[bold]Leftovers Scan Complete[/]\n\n"
            f"  Leftovers found: [yellow]{len(results.items)}[/]\n"
            f"  Sources scanned: [cyan]{len(by_source)}[/]\n"
            f"  Total size: [green]{format_size(results.total_size)}[/]\n\n"
            f"[bold]By Source:[/]\n{summary_text}",
            title="App Leftovers Cleanup",
            border_style="green",
        )
    )

    if results.scan_errors:
        console.print(
            f"\n[dim]({len(results.scan_errors)} errors during scan - "
            f"some directories were inaccessible)[/]"
        )


def handle_leftovers_cleanup(console: Console, args: argparse.Namespace) -> None:
    """Handle leftover app data cleanup workflow."""
    if not is_macos():
        console.print("\n[yellow]Leftovers cleanup is only available on macOS.[/]")
        return

    config = get_config()
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)
    use_trash = (
        config.use_trash if json_mode else check_trash_availability(console, config.use_trash)
    )

    scanner = LeftoverScanner()
    scan_console = Console(stderr=True) if json_mode else console

    with get_progress_context(scan_console) as progress:
        task = progress.add_task("Scanning for app leftovers...", total=None)

        def scan_progress(count: int, name: str) -> None:
            progress.update(
                task,
                description=f"Scanning... ({count} leftovers found, checking: {name})",
            )

        results = scanner.scan(progress_callback=scan_progress)
        progress.update(task, completed=100, total=100)

    if json_mode:
        dump_json(leftovers_scan_payload(results))
        return

    _display_leftovers_summary(console, results)

    if not results.items:
        console.print("\n[dim]No app leftovers found.[/]")
        record_history(
            "leftovers",
            dry_run=dry_run,
            status="empty",
            scanned_count=len(results.items),
            extra={"found_count": 0},
        )
        return

    selected = select_files_interactive(results.items, title="App Leftovers")

    if selected:
        selected_leftovers = selected

        if confirm_file_deletion(console, selected, use_trash=use_trash):
            deletion_results = perform_file_deletions(
                console,
                selected_leftovers,
                use_trash=use_trash,
                dry_run=dry_run,
                config=config,
            )

            display_file_deletion_results(
                console,
                [(item, success, msg) for item, success, msg in deletion_results],
                use_trash=use_trash,
                dry_run=dry_run,
            )
            reclaimed = sum(
                leftover.size
                for leftover, success, _ in deletion_results
                if success and not dry_run
            )
            record_history(
                "leftovers",
                dry_run=dry_run,
                status="completed",
                selected_count=len(selected_leftovers),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=len(results.items),
                extra={"found_count": len(results.items)},
            )
        else:
            console.print("\n[yellow]Leftovers cleanup cancelled.[/]")
            record_history(
                "leftovers",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(selected_leftovers),
                scanned_count=len(results.items),
                extra={"found_count": len(results.items)},
            )
    else:
        console.print("\n[dim]No leftovers selected for cleanup.[/]")
        record_history(
            "leftovers",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=len(results.items),
            extra={"found_count": len(results.items)},
        )
