"""Disk explorer cleanup journey and non-interactive export."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

from ..config import get_config
from ..json_output import disk_scan_payload
from ..scanners import DiskExplorer
from ..formatting import format_size
from ..models import SIZE_LOADING
from ..filesystem import trash_available, validate_directory
from ..ui.journey import (
    BusyScreen,
    ReviewItem,
    ReviewScreen,
    ResultsScreen,
    choose_directory,
    confirm_dangerous,
)
from .common import delete_item, execute_items, record_history, record_cleanup


def handle_disk_explorer(console, args):
    from ..ui.explorer import DiskExplorerUI

    config = get_config()
    start_path = Path(config.start_path).expanduser()
    if getattr(args, "directory", None):
        valid, value = validate_directory(args.directory)
        if not valid:
            console.print(f"[red]Error:[/] {value}")
            return
        start_path = value
    if getattr(args, "json", False):
        export_disk_scan(start_path, "-")
        return
    explorer = DiskExplorer(
        min_size_bytes=config.min_size_mb * 1024 * 1024,
        ignored_paths=[Path(path) for path in config.ignored_paths],
    )
    if config.cache_enabled:
        explorer.load_cache(max_age_hours=config.cache_max_age_hours)
    ui = DiskExplorerUI(explorer, start_path=start_path)
    refresh = True
    try:
        while True:
            selected = ui.run(refresh=refresh)
            refresh = False
            if not selected:
                return

            paths = sorted(selected)
            paths = [
                path
                for path in paths
                if not any(parent in selected for parent in path.parents)
            ]

            def measure(update):
                unknown = [
                    path
                    for path in paths
                    if path.is_dir() and explorer.get_cached_size(path) is None
                ]
                explorer.calculate_sizes_parallel(
                    unknown, callback=lambda path, size: update(str(path))
                )
                rows = []
                for path in paths:
                    try:
                        size = (
                            explorer.get_cached_size(path)
                            if path.is_dir()
                            else path.lstat().st_size
                        )
                    except OSError:
                        size = 0
                    rows.append(ReviewItem(path, max(0, size or 0)))
                return rows

            items = (
                BusyScreen("Preparing deletion review", str(ui.current_path))
                .within(ui)
                .run(measure)
            )
            unavailable = config.use_trash and not trash_available()
            use_trash = config.use_trash and not unavailable
            if (
                ReviewScreen(
                    items,
                    use_trash,
                    str(ui.current_path),
                    trash_unavailable=unavailable,
                )
                .within(ui)
                .run()
                != "confirm"
            ):
                record_history("explore", status="cancelled", selected_count=len(items))
                continue
            dangerous = [path for path in paths if explorer.is_dangerous(path)]
            if dangerous and not confirm_dangerous(dangerous):
                continue
            outcomes = (
                BusyScreen(
                    "Moving to Trash" if use_trash else "Permanently deleting",
                    str(ui.current_path),
                )
                .within(ui)
                .run(
                    lambda update: execute_items(
                        items,
                        use_trash,
                        lambda item, trash: delete_item(
                            item.path, trash, config=config
                        ),
                        update,
                    )
                )
            )
            record_cleanup("explore", outcomes, use_trash)
            ui.selected = {item.path for item, ok, _ in outcomes if not ok}

            for item, ok, _ in outcomes:
                if ok:
                    explorer.invalidate_cache(item.path)
            result_page = ResultsScreen(
                outcomes, use_trash, str(ui.current_path)
            ).within(ui)
            while True:
                choice = result_page.run()
                if choice in ("back", "menu"):
                    return
                if choice == "directory":
                    root = choose_directory(ui.current_path)
                    if root is None:
                        continue
                    ui = DiskExplorerUI(explorer, start_path=root)
                refresh = True
                break
    finally:
        if config.cache_enabled:
            explorer.save_cache()


def export_disk_scan(path: Path, output: str) -> None:
    """
    Scan a directory and export results to JSON.

    This is a non-interactive mode for scripting and automation.

    Args:
        path: Directory to scan
        output: Output file path, or "-" for stdout
    """

    console = Console(stderr=True) if output == "-" else Console()

    explorer = DiskExplorer(min_size_bytes=0)

    console.print(f"\n[bold blue]Scanning:[/] {path}")

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

            explorer.calculate_sizes_parallel(
                paths_to_calculate,
                callback=on_size_calculated,
                max_workers=4,
            )

            for item in items:
                if item.is_dir and item.size == SIZE_LOADING:
                    cached_size = explorer.get_cached_size(item.path)
                    if cached_size is not None:
                        item.size = cached_size

        progress.update(scan_task, completed=100, total=100)

    export_data = disk_scan_payload(path, items)

    json_output = json.dumps(export_data, indent=2)

    if output == "-":
        print(json_output)
    else:
        output_path = Path(output)
        output_path.write_text(json_output)
        console.print(f"\n[bold green]Exported to:[/] {output_path}")
        console.print(
            f"  Total size: [cyan]{format_size(export_data['total_size'])}[/]"
        )
        console.print(f"  Items: [cyan]{len(export_data['items'])}[/]")
