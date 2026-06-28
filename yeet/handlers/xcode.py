"""Handler for Xcode cleanup workflow."""

from __future__ import annotations

import argparse
import subprocess

from rich.console import Console
from rich.panel import Panel

from ..scanner import XcodeScanner
from ..utils import (
    XcodeItem,
    XcodeItemType,
    XcodeScanResults,
    delete_directory,
    format_size,
    is_macos,
)
from ..ui.tables import display_xcode_scan_summary, display_xcode_deletion_results
from ..ui.selector import select_xcode_items_interactive
from ..json_output import xcode_scan_payload, dump_json

from .common import get_progress_context, get_deletion_progress_context
from .common import record_history


def run_xcode_scan(
    console: Console,
) -> XcodeScanResults:
    """Run the Xcode scan with progress display."""
    scanner = XcodeScanner()

    with get_progress_context(console) as progress:
        scan_task = progress.add_task(
            "Scanning Xcode data...",
            total=None,
        )

        def scan_progress(count: int, name: str) -> None:
            progress.update(
                scan_task,
                description=f"Scanning... ({count} items found, checking: {name})",
            )

        results = scanner.scan(progress_callback=scan_progress)
        progress.update(scan_task, completed=100, total=100)

    return results


def perform_xcode_deletions(
    console: Console,
    items: list[XcodeItem],
    dry_run: bool = False,
) -> list[tuple[XcodeItem, bool, str]]:
    """Delete selected Xcode items with progress."""
    results: list[tuple[XcodeItem, bool, str]] = []

    with get_deletion_progress_context(console) as progress:
        task = progress.add_task("Cleaning up...", total=len(items))

        for item in items:
            progress.update(
                task,
                description=f"{'Would delete' if dry_run else 'Deleting'}: {item.name}",
            )

            # Simulator runtimes need special handling via simctl
            if item.item_type == XcodeItemType.SIMULATOR_RUNTIME:
                uuid = item.app_info.get("uuid") if item.app_info else None
                if uuid:
                    if dry_run:
                        success, msg = (
                            True,
                            f"Dry run: would delete runtime {item.name}",
                        )
                    else:
                        try:
                            result = subprocess.run(
                                ["xcrun", "simctl", "runtime", "delete", uuid],
                                capture_output=True,
                                text=True,
                                timeout=60,
                            )
                            if result.returncode == 0:
                                success, msg = True, f"Deleted runtime: {item.name}"
                            else:
                                success, msg = (
                                    False,
                                    result.stderr.strip() or "Failed to delete runtime",
                                )
                        except subprocess.SubprocessError as e:
                            success, msg = False, f"Failed to run simctl: {e}"
                else:
                    success, msg = False, "No UUID found for runtime"
            else:
                # Regular directory deletion
                if dry_run:
                    success, msg = True, f"Dry run: would delete {item.path}"
                else:
                    success, msg = delete_directory(item.path)

            results.append((item, success, msg))
            progress.advance(task)

    return results


def confirm_xcode_deletion(console: Console, items: list[XcodeItem]) -> bool:
    """Show summary and confirm Xcode item deletion."""
    from rich.prompt import Confirm

    total_size = sum(item.size for item in items)

    # Group by type for display
    by_type: dict[str, list[XcodeItem]] = {}
    for item in items:
        type_name = item.item_type.value
        if type_name not in by_type:
            by_type[type_name] = []
        by_type[type_name].append(item)

    summary_lines = []
    for type_name, type_items in by_type.items():
        type_size = sum(i.size for i in type_items)
        summary_lines.append(
            f"  {type_name}: {len(type_items)} items ({format_size(type_size)})"
        )

    console.print()
    console.print(
        Panel(
            f"[bold red]About to delete {len(items)} Xcode item(s):[/]\n\n"
            + "\n".join(summary_lines)
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]\n\n"
            + "[dim]Note: Device support and simulators may be re-downloaded when needed.[/]",
            title="Xcode Cleanup",
            border_style="red",
        )
    )
    console.print()

    return Confirm.ask(
        "[bold red]Are you sure you want to delete these items?[/]",
        default=False,
        console=console,
    )


def handle_xcode_cleanup(console: Console, args: argparse.Namespace) -> None:
    """Handle the Xcode cleanup workflow."""
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)

    if not is_macos():
        console.print("\n[yellow]Xcode cleanup is only available on macOS.[/]")
        return

    # Run scan
    scan_console = Console(stderr=True) if json_mode else console
    if not json_mode:
        console.print("\n[dim]Scanning Xcode data directories...[/]")
        console.print()
    results = run_xcode_scan(scan_console)

    if json_mode:
        dump_json(xcode_scan_payload(results))
        return

    # Display summary
    display_xcode_scan_summary(console, results)

    if not results.items:
        console.print("\n[dim]No Xcode items found to clean up.[/]")
        record_history(
            "xcode",
            dry_run=dry_run,
            status="empty",
            scanned_count=len(results.items),
            extra={"found_count": 0},
        )
        return

    # Interactive selection
    items_to_delete = select_xcode_items_interactive(
        results.items,
        title="Xcode Cleanup",
    )

    if items_to_delete:
        if confirm_xcode_deletion(console, items_to_delete):
            deletion_results = perform_xcode_deletions(
                console, items_to_delete, dry_run=dry_run
            )
            display_xcode_deletion_results(console, deletion_results, dry_run=dry_run)
            reclaimed = sum(
                item.size
                for item, success, _ in deletion_results
                if success and not dry_run
            )
            record_history(
                "xcode",
                dry_run=dry_run,
                status="completed",
                selected_count=len(items_to_delete),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=len(results.items),
                extra={"found_count": len(results.items)},
            )
        else:
            console.print("\n[yellow]Xcode cleanup cancelled.[/]")
            record_history(
                "xcode",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(items_to_delete),
                scanned_count=len(results.items),
                extra={"found_count": len(results.items)},
            )
    else:
        console.print("\n[dim]No items selected for cleanup.[/]")
        record_history(
            "xcode",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=len(results.items),
            extra={"found_count": len(results.items)},
        )
