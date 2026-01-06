"""Handler for disk explorer workflow."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

from ..config import get_config
from ..scanner import DiskExplorer
from ..utils import format_size, SIZE_LOADING

from .common import delete_item, get_deletion_progress_context, check_trash_availability


def handle_disk_explorer(console: Console, args: argparse.Namespace) -> None:
    """Handle the disk explorer workflow."""
    from ..ui.explorer import DiskExplorerUI

    # Get config for settings
    config = get_config()
    start_path = Path(config.start_path).expanduser()
    use_trash = check_trash_availability(console, config.use_trash)

    console.print("\n[dim]Starting disk explorer...[/]")

    # Create explorer using config settings
    explorer = DiskExplorer(min_size_bytes=config.min_size_mb * 1024 * 1024)

    # Load cached sizes for faster startup
    if config.cache_enabled:
        loaded = explorer.load_cache(max_age_hours=config.cache_max_age_hours)
        if loaded > 0:
            console.print(f"[dim]Loaded {loaded} cached sizes[/]")

    ui = DiskExplorerUI(explorer, start_path=start_path)

    # Run the explorer
    selected_paths = ui.run()

    # Save cache for next time
    if config.cache_enabled:
        explorer.save_cache()

    if not selected_paths:
        console.print("\n[dim]No items selected for deletion.[/]")
        return

    # Calculate total size
    total_size = sum(explorer.get_cached_size(p) or 0 for p in selected_paths)

    # Check for dangerous paths
    dangerous_paths = [p for p in selected_paths if explorer.is_dangerous(p)]

    if dangerous_paths:
        console.print("\n[bold red]WARNING: You are about to delete system paths:[/]")
        for p in dangerous_paths:
            console.print(f"  [red]{p}[/]")
        console.print("\n[bold red]This may break your system or applications![/]")

        confirm_text = console.input("\n[bold red]Type 'yes' to confirm: [/]")
        if confirm_text.strip().lower() != "yes":
            console.print("[yellow]Deletion cancelled.[/]")
            return

    # Determine action text based on trash setting
    action_verb = "move to trash" if use_trash else "delete permanently"
    action_noun = "Moved to trash" if use_trash else "Deleted"

    # Show confirmation
    console.print(
        Panel(
            f"[bold red]About to {action_verb} {len(selected_paths)} item(s):[/]\n\n"
            + "\n".join(
                f"  - {p} ({format_size(explorer.get_cached_size(p) or 0)})"
                for p in sorted(selected_paths)[:10]
            )
            + (
                f"\n  ... and {len(selected_paths) - 10} more"
                if len(selected_paths) > 10
                else ""
            )
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]",
            title="Deletion Summary",
            border_style="red",
        )
    )

    # Use appropriate confirmation message
    confirm_msg = (
        "[bold red]Are you sure you want to move these items to trash?[/]"
        if use_trash
        else "[bold red]Are you sure you want to delete these items permanently?[/]"
    )

    if not Confirm.ask(
        confirm_msg,
        default=False,
        console=console,
    ):
        console.print("[yellow]Deletion cancelled.[/]")
        return

    # Perform deletions
    deleted_count = 0
    failed_count = 0
    reclaimed_size = 0

    action_word = "Moving to trash" if use_trash else "Deleting"

    with get_deletion_progress_context(console) as progress:
        task = progress.add_task(f"{action_word}...", total=len(selected_paths))

        for path in selected_paths:
            progress.update(task, description=f"{action_word}: {path.name}")
            size = explorer.get_cached_size(path) or 0

            success, msg = delete_item(path, use_trash)

            if success:
                deleted_count += 1
                reclaimed_size += size
            else:
                failed_count += 1
                console.print(f"[red]Failed:[/] {path} - {msg}")

            progress.advance(task)

    # Show results
    console.print()
    result_title = "Cleanup Summary"
    result_action = action_noun

    result_text = (
        f"[bold]{result_action} Complete[/]\n\n"
        f"  Items {result_action.lower()}: [green]{deleted_count}[/]"
        f"{f' ([red]{failed_count} failed[/])' if failed_count else ''}\n\n"
        f"  [bold green]Space reclaimed: {format_size(reclaimed_size)}[/]"
    )

    if use_trash and deleted_count > 0:
        result_text += (
            "\n\n[dim]Items moved to trash. You can restore them from "
            "your system trash if needed.[/]"
        )

    console.print(
        Panel(
            result_text,
            title=result_title,
            border_style="green",
        )
    )


def export_disk_scan(path: Path, output: str) -> None:
    """
    Scan a directory and export results to JSON.

    This is a non-interactive mode for scripting and automation.

    Args:
        path: Directory to scan
        output: Output file path, or "-" for stdout
    """
    # Use stderr for progress when outputting to stdout
    console = Console(stderr=True) if output == "-" else Console()

    # Create explorer with no minimum size for export (include everything)
    explorer = DiskExplorer(min_size_bytes=0)

    console.print(f"\n[bold blue]Scanning:[/] {path}")

    # Scan the directory
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        scan_task = progress.add_task("Scanning directory...", total=None)

        items = explorer.scan_directory(path, include_small=True)

        # Get paths that need size calculation
        paths_to_calculate = [
            item.path for item in items if item.is_dir and item.size == SIZE_LOADING
        ]

        if paths_to_calculate:
            progress.update(
                scan_task,
                description=f"Calculating sizes for {len(paths_to_calculate)} directories...",
            )

            calculated_count = 0
            total_count = len(paths_to_calculate)

            def on_size_calculated(p: Path, size: int) -> None:
                nonlocal calculated_count
                calculated_count += 1
                progress.update(
                    scan_task,
                    description=f"Calculating sizes... ({calculated_count}/{total_count})",
                )

            # Calculate sizes in parallel
            explorer.calculate_sizes_parallel(
                paths_to_calculate,
                callback=on_size_calculated,
                max_workers=4,
            )

            # Update items with calculated sizes
            for item in items:
                if item.is_dir and item.size == SIZE_LOADING:
                    cached_size = explorer.get_cached_size(item.path)
                    if cached_size is not None:
                        item.size = cached_size

        progress.update(scan_task, completed=100, total=100)

    # Calculate total size
    total_size = sum(item.size for item in items if item.size > 0)

    # Build export data
    export_items = []
    for item in items:
        if item.size <= 0:
            continue

        percent_of_parent = (item.size / total_size * 100) if total_size > 0 else 0

        export_items.append(
            {
                "path": str(item.path),
                "name": item.name,
                "size": item.size,
                "is_dir": item.is_dir,
                "modified": item.modified.isoformat() if item.modified else None,
                "percent_of_parent": round(percent_of_parent, 2),
            }
        )

    # Sort by size descending
    export_items.sort(key=lambda x: x["size"], reverse=True)

    export_data = {
        "scan_date": datetime.now().isoformat(),
        "root_path": str(path),
        "total_size": total_size,
        "items": export_items,
    }

    # Output JSON
    json_output = json.dumps(export_data, indent=2)

    if output == "-":
        # Write to stdout
        print(json_output)
    else:
        # Write to file
        output_path = Path(output)
        output_path.write_text(json_output)
        console.print(f"\n[bold green]Exported to:[/] {output_path}")
        console.print(f"  Total size: [cyan]{format_size(total_size)}[/]")
        console.print(f"  Items: [cyan]{len(export_items)}[/]")
