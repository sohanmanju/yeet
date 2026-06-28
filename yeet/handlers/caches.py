"""Handler for cache scan workflow."""

from __future__ import annotations

import argparse
import platform

from rich.console import Console
from rich.panel import Panel

from ..config import get_config
from ..scanner import CacheScanner
from ..utils import (
    CacheLocation,
    CacheScanResults,
    format_size,
    trash_available,
)
from ..ui.tables import display_cache_scan_summary, display_cache_deletion_results
from ..ui.selector import select_caches_interactive
from ..json_output import cache_scan_payload, dump_json

from .common import (
    delete_item,
    get_progress_context,
    get_deletion_progress_context,
    check_trash_availability,
    record_history,
)


def run_cache_scan(
    console: Console,
    min_size_mb: int = 1,
) -> CacheScanResults:
    """Run the cache scan with progress display."""
    scanner = CacheScanner()

    with get_progress_context(console) as progress:
        scan_task = progress.add_task(
            "Scanning for caches...",
            total=None,
        )

        def scan_progress(count: int, name: str) -> None:
            progress.update(
                scan_task,
                description=f"Scanning... ({count} caches found, checking: {name})",
            )

        results = scanner.scan(progress_callback=scan_progress, min_size_mb=min_size_mb)
        progress.update(scan_task, completed=100, total=100)

    return results


def perform_cache_deletions(
    console: Console,
    caches: list[CacheLocation],
    use_trash: bool = False,
    dry_run: bool = False,
    config=None,
) -> list[tuple[CacheLocation, bool, str]]:
    """Delete selected caches with progress."""
    results: list[tuple[CacheLocation, bool, str]] = []

    action_word = "Moving to trash" if use_trash and trash_available() else "Clearing"

    with get_deletion_progress_context(console) as progress:
        task = progress.add_task(f"{action_word} caches...", total=len(caches))

        for cache in caches:
            progress.update(task, description=f"{action_word}: {cache.name}")
            success, msg = delete_item(
                cache.path,
                use_trash,
                dry_run=dry_run,
                config=config,
            )
            results.append((cache, success, msg))
            progress.advance(task)

    return results


def confirm_cache_deletion(
    console: Console, caches: list[CacheLocation], use_trash: bool = False
) -> bool:
    """Show summary and confirm cache deletion."""
    from rich.prompt import Confirm

    total_size = sum(c.size for c in caches)

    action_verb = "move to trash" if use_trash else "clear"

    console.print()
    console.print(
        Panel(
            f"[bold red]About to {action_verb} {len(caches)} cache(s):[/]\n\n"
            + "\n".join(f"  - {c.name} ({c.size_formatted})" for c in caches[:10])
            + (f"\n  ... and {len(caches) - 10} more" if len(caches) > 10 else "")
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]\n\n"
            + "[dim]Note: Some caches will be recreated as you use apps.[/]",
            title="Cache Cleanup",
            border_style="red",
        )
    )
    console.print()

    confirm_msg = (
        "[bold red]Are you sure you want to move these caches to trash?[/]"
        if use_trash
        else "[bold red]Are you sure you want to clear these caches?[/]"
    )

    return Confirm.ask(
        confirm_msg,
        default=False,
        console=console,
    )


def handle_cache_scan(console: Console, args: argparse.Namespace) -> None:
    """Handle the cache scan workflow."""
    # Get config for trash setting
    config = get_config()
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)
    use_trash = (
        config.use_trash if json_mode else check_trash_availability(console, config.use_trash)
    )

    # Show OS info
    os_name = platform.system()
    scan_console = Console(stderr=True) if json_mode else console
    if not json_mode:
        console.print(f"\n[dim]Detected OS: {os_name}[/]")

    # Run scan
    if not json_mode:
        console.print()
    results = run_cache_scan(scan_console, min_size_mb=args.min_cache_size)

    if json_mode:
        dump_json(cache_scan_payload(results))
        return

    # Display summary
    display_cache_scan_summary(console, results)

    if not results.caches:
        console.print("\n[dim]No significant caches found.[/]")
        record_history(
            "caches",
            dry_run=dry_run,
            status="empty",
            scanned_count=len(results.caches),
            extra={"found_count": 0},
        )
        return

    # Interactive selection
    caches_to_clear = select_caches_interactive(
        results.caches,
        title="System Caches (sorted by size)",
    )

    if caches_to_clear:
        if confirm_cache_deletion(console, caches_to_clear, use_trash=use_trash):
            deletion_results = perform_cache_deletions(
                console,
                caches_to_clear,
                use_trash=use_trash,
                dry_run=dry_run,
                config=config,
            )
            display_cache_deletion_results(
                console,
                deletion_results,
                use_trash=use_trash,
                dry_run=dry_run,
            )
            reclaimed = sum(
                c.size for c, success, _ in deletion_results if success and not dry_run
            )
            record_history(
                "caches",
                dry_run=dry_run,
                status="completed",
                selected_count=len(caches_to_clear),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=len(results.caches),
                extra={"found_count": len(results.caches)},
            )
        else:
            console.print("\n[yellow]Cache cleanup cancelled.[/]")
            record_history(
                "caches",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(caches_to_clear),
                scanned_count=len(results.caches),
                extra={"found_count": len(results.caches)},
            )
    else:
        console.print("\n[dim]No caches selected for cleanup.[/]")
        record_history(
            "caches",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=len(results.caches),
            extra={"found_count": len(results.caches)},
        )
