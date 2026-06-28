"""Handler for stale projects workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from ..config import get_config
from ..scanner import ProjectScanner
from ..utils import (
    Project,
    ScanResults,
    trash_available,
)
from ..ui.prompts import get_directory_prompt, confirm_deletion
from ..ui.tables import display_scan_summary, display_deletion_results
from ..ui.selector import select_projects_interactive
from ..json_output import project_scan_payload, dump_json

from .common import (
    delete_item,
    get_progress_context,
    get_deletion_progress_context,
    check_trash_availability,
    record_history,
)


def run_project_scan(
    console: Console,
    root: Path,
    days_threshold: int = 90,
) -> ScanResults:
    """Run the project scan with progress display."""
    scanner = ProjectScanner(
        days_threshold=days_threshold,
        include_all=False,
    )

    with get_progress_context(console) as progress:
        scan_task = progress.add_task(
            "Scanning for projects...",
            total=None,
        )

        def scan_progress(count: int, name: str) -> None:
            progress.update(
                scan_task,
                description=f"Scanning... ({count} projects, current: {name})",
            )

        results = scanner.scan(root, progress_callback=scan_progress)
        progress.update(scan_task, completed=100, total=100)

    return results


def perform_project_deletions(
    console: Console,
    projects: list[Project],
    use_trash: bool = False,
    dry_run: bool = False,
    config=None,
) -> list[tuple[Project, bool, str]]:
    """Delete selected projects with progress."""
    results: list[tuple[Project, bool, str]] = []

    action_word = "Moving to trash" if use_trash and trash_available() else "Deleting"

    with get_deletion_progress_context(console) as progress:
        task = progress.add_task(f"{action_word}...", total=len(projects))

        for project in projects:
            progress.update(task, description=f"{action_word}: {project.name}")
            success, msg = delete_item(
                project.path,
                use_trash,
                dry_run=dry_run,
                config=config,
            )
            results.append((project, success, msg))
            progress.advance(task)

    return results


def handle_stale_projects(console: Console, args: argparse.Namespace) -> None:
    """Handle the stale projects workflow."""
    # Get config for trash setting
    config = get_config()
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)
    use_trash = (
        config.use_trash if json_mode else check_trash_availability(console, config.use_trash)
    )

    # Get directory
    if json_mode:
        if args.directory:
            from ..utils import validate_directory

            is_valid, result = validate_directory(args.directory)
            if not is_valid:
                console.print(f"[red]Error:[/] {result}")
                return
            root = result
        else:
            root = Path(config.start_path).expanduser()
    elif args.directory:
        from ..utils import validate_directory

        is_valid, result = validate_directory(args.directory)
        if not is_valid:
            console.print(f"[red]Error:[/] {result}")
            return
        root = result
        args.directory = None
    else:
        root = get_directory_prompt(console)

    # Run scan
    scan_console = Console(stderr=True) if json_mode else console
    if not json_mode:
        console.print()
    results = run_project_scan(scan_console, root, days_threshold=args.days)

    if json_mode:
        dump_json(project_scan_payload(results))
        return

    # Display results
    display_scan_summary(console, results)

    if not results.projects:
        console.print("\n[dim]No stale projects found.[/]")
        record_history(
            "projects",
            dry_run=dry_run,
            status="empty",
            scanned_count=results.total_projects_scanned,
            extra={"found_count": 0},
        )
        return

    # Sort and select
    sorted_projects = sorted(results.projects, key=lambda p: p.days_stale, reverse=True)

    projects_to_delete = select_projects_interactive(
        sorted_projects,
        title=f"Stale Projects (>{args.days} days inactive)",
    )

    if projects_to_delete:
        if confirm_deletion(console, projects_to_delete, use_trash=use_trash):
            deletion_results = perform_project_deletions(
                console,
                projects_to_delete,
                use_trash=use_trash,
                dry_run=dry_run,
                config=config,
            )
            display_deletion_results(
                console, deletion_results, use_trash=use_trash, dry_run=dry_run
            )
            reclaimed = sum(
                p.total_size for p, success, _ in deletion_results if success and not dry_run
            )
            record_history(
                "projects",
                dry_run=dry_run,
                status="completed",
                selected_count=len(projects_to_delete),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=results.total_projects_scanned,
                extra={"found_count": len(results.projects)},
            )
        else:
            console.print("\n[yellow]Deletion cancelled.[/]")
            record_history(
                "projects",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(projects_to_delete),
                scanned_count=results.total_projects_scanned,
                extra={"found_count": len(results.projects)},
            )
    else:
        console.print("\n[dim]No projects selected for deletion.[/]")
        record_history(
            "projects",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=results.total_projects_scanned,
            extra={"found_count": len(results.projects)},
        )
