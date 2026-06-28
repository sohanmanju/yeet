"""Handler for project artifact purge workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ..config import get_config
from ..json_output import dump_json, purge_scan_payload
from ..scanner import PurgeScanner
from ..utils import format_size, validate_directory
from ..ui.selector import select_files_interactive

from .files import (
    display_file_deletion_results,
    confirm_file_deletion,
    perform_file_deletions,
)

from .common import (
    get_progress_context,
    check_trash_availability,
    record_history,
)


def _display_purge_summary(console: Console, results) -> None:
    console.print()

    by_project = results.by_project
    project_lines = []
    project_totals = {
        project_root: sum(artifact.size for artifact in artifacts)
        for project_root, artifacts in by_project.items()
    }
    for project_root, total in sorted(
        project_totals.items(), key=lambda item: item[1], reverse=True
    )[:10]:
        artifacts = by_project[project_root]
        project_lines.append(
            f"  {project_root.name}: {len(artifacts)} artifacts ({format_size(total)})"
        )

    summary_text = "\n".join(project_lines) if project_lines else "  No artifacts found"

    console.print(
        Panel(
            f"[bold]Purge Scan Complete[/]\n\n"
            f"  Artifacts found: [yellow]{len(results.artifacts)}[/]\n"
            f"  Projects impacted: [cyan]{len(by_project)}[/]\n"
            f"  Total size: [green]{format_size(results.total_size)}[/]\n\n"
            f"[bold]By Project:[/]\n{summary_text}",
            title="Project Artifact Cleanup",
            border_style="green",
        )
    )

    if results.scan_errors:
        console.print(
            f"\n[dim]({len(results.scan_errors)} errors during scan - "
            f"some directories were inaccessible)[/]"
        )


def handle_purge(console: Console, args: argparse.Namespace) -> None:
    """Handle the project artifact purge workflow."""
    config = get_config()
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)
    use_trash = (
        config.use_trash
        if json_mode
        else check_trash_availability(console, config.use_trash)
    )

    if args.directory:
        is_valid, result = validate_directory(args.directory)
        if not is_valid:
            console.print(f"[red]Error:[/] {result}")
            return
        root = result
    else:
        root = Path(config.start_path).expanduser()

    scanner = PurgeScanner()
    scan_console = Console(stderr=True) if json_mode else console

    with get_progress_context(scan_console) as progress:
        task = progress.add_task("Scanning for project artifacts...", total=None)

        def scan_progress(count: int, name: str) -> None:
            progress.update(
                task,
                description=f"Scanning... ({count} artifacts found, checking: {name})",
            )

        results = scanner.scan(root, progress_callback=scan_progress)
        progress.update(task, completed=100, total=100)

    if json_mode:
        dump_json(purge_scan_payload(root, results))
        return

    _display_purge_summary(console, results)

    if not results.artifacts:
        console.print("\n[dim]No project artifacts found.[/]")
        record_history(
            "purge",
            dry_run=dry_run,
            status="empty",
            scanned_count=len(results.artifacts),
            extra={"found_count": 0},
        )
        return

    artifacts_to_delete = select_files_interactive(
        results.artifacts,
        title="Project Artifacts (build outputs and caches)",
    )

    if artifacts_to_delete:
        if confirm_file_deletion(console, artifacts_to_delete, use_trash=use_trash):
            deletion_results = perform_file_deletions(
                console,
                artifacts_to_delete,
                use_trash=use_trash,
                dry_run=dry_run,
                config=config,
            )

            display_file_deletion_results(
                console,
                deletion_results,
                use_trash=use_trash,
                dry_run=dry_run,
            )
            reclaimed = sum(
                artifact.size
                for artifact, success, _ in deletion_results
                if success and not dry_run
            )
            record_history(
                "purge",
                dry_run=dry_run,
                status="completed",
                selected_count=len(artifacts_to_delete),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=len(results.artifacts),
                extra={"found_count": len(results.artifacts)},
            )
        else:
            console.print("\n[yellow]Purge cancelled.[/]")
            record_history(
                "purge",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(artifacts_to_delete),
                scanned_count=len(results.artifacts),
                extra={"found_count": len(results.artifacts)},
            )
    else:
        console.print("\n[dim]No artifacts selected for cleanup.[/]")
        record_history(
            "purge",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=len(results.artifacts),
            extra={"found_count": len(results.artifacts)},
        )
