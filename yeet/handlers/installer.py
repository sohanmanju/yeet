"""Handler for installer cleanup workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ..config import get_config
from ..json_output import dump_json, installer_scan_payload
from ..scanner import InstallerScanner
from ..utils import format_size, validate_directory
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


def _display_installer_summary(console: Console, results) -> None:
    console.print()

    by_source = results.by_source
    source_lines = []
    source_totals = {
        source: sum(item.size for item in items) for source, items in by_source.items()
    }
    for source, total in sorted(source_totals.items(), key=lambda item: item[1], reverse=True):
        items = by_source[source]
        source_lines.append(f"  {source}: {len(items)} installers ({format_size(total)})")

    summary_text = "\n".join(source_lines) if source_lines else "  No installers found"

    console.print(
        Panel(
            f"[bold]Installer Scan Complete[/]\n\n"
            f"  Installers found: [yellow]{len(results.items)}[/]\n"
            f"  Sources scanned: [cyan]{len(by_source)}[/]\n"
            f"  Total size: [green]{format_size(results.total_size)}[/]\n\n"
            f"[bold]By Source:[/]\n{summary_text}",
            title="Installer Cleanup",
            border_style="green",
        )
    )

    if results.scan_errors:
        console.print(
            f"\n[dim]({len(results.scan_errors)} errors during scan - "
            f"some directories were inaccessible)[/]"
        )


def handle_installer_cleanup(console: Console, args: argparse.Namespace) -> None:
    """Handle installer cleanup workflow."""
    config = get_config()
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)
    use_trash = (
        config.use_trash if json_mode else check_trash_availability(console, config.use_trash)
    )

    root = None
    if args.directory:
        is_valid, result = validate_directory(args.directory)
        if not is_valid:
            console.print(f"[red]Error:[/] {result}")
            return
        root = result

    scanner = InstallerScanner()
    scan_console = Console(stderr=True) if json_mode else console

    with get_progress_context(scan_console) as progress:
        task = progress.add_task("Scanning for installers...", total=None)

        def scan_progress(count: int, name: str) -> None:
            progress.update(
                task,
                description=f"Scanning... ({count} installers found, checking: {name})",
            )

        results = scanner.scan(root, progress_callback=scan_progress)
        progress.update(task, completed=100, total=100)

    if json_mode:
        dump_json(installer_scan_payload(root, results))
        return

    _display_installer_summary(console, results)

    if not results.items:
        console.print("\n[dim]No installers found.[/]")
        record_history(
            "installer",
            dry_run=dry_run,
            status="empty",
            scanned_count=len(results.items),
            extra={"found_count": 0},
        )
        return

    selected = select_files_interactive(results.items, title="Installer Files")

    if selected:
        selected_installers = selected

        if confirm_file_deletion(console, selected, use_trash=use_trash):
            deletion_results = perform_file_deletions(
                console,
                selected_installers,
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
                installer.size
                for installer, success, _ in deletion_results
                if success and not dry_run
            )
            record_history(
                "installer",
                dry_run=dry_run,
                status="completed",
                selected_count=len(selected_installers),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=len(results.items),
                extra={"found_count": len(results.items)},
            )
        else:
            console.print("\n[yellow]Installer cleanup cancelled.[/]")
            record_history(
                "installer",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(selected_installers),
                scanned_count=len(results.items),
                extra={"found_count": len(results.items)},
            )
    else:
        console.print("\n[dim]No installers selected for cleanup.[/]")
        record_history(
            "installer",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=len(results.items),
            extra={"found_count": len(results.items)},
        )
