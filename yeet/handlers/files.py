"""Handler for large files workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ..config import get_config
from ..scanner import LargeFileScanner
from ..utils import (
    LargeFileScanResults,
    SelectableItem,
    format_size,
    trash_available,
)
from ..ui.prompts import get_directory_prompt
from ..ui.selector import select_files_interactive
from ..json_output import large_file_scan_payload, dump_json

from .common import (
    delete_item,
    get_progress_context,
    get_deletion_progress_context,
    check_trash_availability,
    record_history,
)


def run_large_file_scan(
    console: Console,
    root: Path,
    min_size_mb: int = 25,
) -> LargeFileScanResults:
    """Run the large file scan with progress display."""
    scanner = LargeFileScanner(min_size_mb=min_size_mb)

    with get_progress_context(console) as progress:
        scan_task = progress.add_task(
            "Scanning for large files...",
            total=None,
        )

        def scan_progress(files_scanned: int, large_found: int, name: str) -> None:
            progress.update(
                scan_task,
                description=f"Scanning... ({files_scanned:,} files, {large_found} large)",
            )

        results = scanner.scan(root, progress_callback=scan_progress)
        progress.update(scan_task, completed=100, total=100)

    return results


def perform_file_deletions(
    console: Console,
    files: list[SelectableItem],
    use_trash: bool = False,
    dry_run: bool = False,
    config=None,
) -> list[tuple[SelectableItem, bool, str]]:
    """Delete selected files with progress."""
    results: list[tuple[SelectableItem, bool, str]] = []

    action_word = "Moving to trash" if use_trash and trash_available() else "Deleting"

    with get_deletion_progress_context(console) as progress:
        task = progress.add_task(f"{action_word}...", total=len(files))

        for file in files:
            progress.update(task, description=f"{action_word}: {file.name}")
            success, msg = delete_item(
                file.path,
                use_trash,
                dry_run=dry_run,
                config=config,
            )
            results.append((file, success, msg))
            progress.advance(task)

    return results


def display_large_file_summary(
    console: Console, results: LargeFileScanResults, min_size_mb: int
) -> None:
    """Display summary of large file scan."""
    console.print()
    console.print(
        Panel(
            f"[bold]Scan Complete[/]\n\n"
            f"  Files scanned: [cyan]{results.total_files_scanned:,}[/]\n"
            f"  Directories scanned: [cyan]{results.total_dirs_scanned:,}[/]\n"
            f"  Large files found (>{min_size_mb}MB): [yellow]{len(results.files)}[/]\n"
            f"  Total size: [green]{format_size(results.total_size)}[/]",
            title="Scan Summary",
            border_style="green",
        )
    )


def display_file_deletion_results(
    console: Console,
    deleted_files: list[tuple[SelectableItem, bool, str]],
    use_trash: bool = False,
    dry_run: bool = False,
) -> None:
    """Display results of file deletion operation."""
    console.print()

    files_success = sum(1 for _, success, _ in deleted_files if success)
    files_failed = len(deleted_files) - files_success

    total_reclaimed = sum(f.size for f, success, _ in deleted_files if success)

    action_noun = (
        ("would be moved to trash" if use_trash else "would be deleted")
        if dry_run
        else ("moved to trash" if use_trash else "deleted")
    )
    title_action = (
        "Dry Run" if dry_run else ("Moved to Trash" if use_trash else "Deletion")
    )
    size_label = "Potential space reclaimed" if dry_run else "Space reclaimed"

    result_text = (
        f"[bold]{title_action} Complete[/]\n\n"
        f"  Files {action_noun}: [green]{files_success}[/]"
        f"{f' ([red]{files_failed} failed[/])' if files_failed else ''}\n\n"
        f"  [bold green]{size_label}: {format_size(total_reclaimed)}[/]"
    )

    if use_trash and files_success > 0 and not dry_run:
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
    failures = [(f, msg) for f, success, msg in deleted_files if not success]

    if failures:
        console.print("\n[bold red]Failed deletions:[/]")
        for file, msg in failures[:10]:
            console.print(f"  [red]File:[/] {file.name} - {msg}")

        if len(failures) > 10:
            console.print(f"  [dim]... and {len(failures) - 10} more failures[/]")


def confirm_file_deletion(
    console: Console, files: list[SelectableItem], use_trash: bool = False
) -> bool:
    """Show summary and confirm file deletion."""
    from rich.prompt import Confirm

    total_size = sum(f.size for f in files)

    action_verb = "move to trash" if use_trash else "delete"

    console.print()
    console.print(
        Panel(
            f"[bold red]About to {action_verb} {len(files)} file(s):[/]\n\n"
            + "\n".join(f"  - {f.name} ({f.size_formatted})" for f in files[:10])
            + (f"\n  ... and {len(files) - 10} more" if len(files) > 10 else "")
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]",
            title="Deletion Summary",
            border_style="red",
        )
    )
    console.print()

    confirm_msg = (
        "[bold red]Are you sure you want to move these files to trash?[/]"
        if use_trash
        else "[bold red]Are you sure you want to delete these files permanently?[/]"
    )

    return Confirm.ask(
        confirm_msg,
        default=False,
        console=console,
    )


def handle_large_files(console: Console, args: argparse.Namespace) -> None:
    """Handle the large files workflow."""
    # Get config for trash setting
    config = get_config()
    dry_run = getattr(args, "dry_run", False)
    json_mode = getattr(args, "json", False)
    use_trash = (
        config.use_trash
        if json_mode
        else check_trash_availability(console, config.use_trash)
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
    results = run_large_file_scan(scan_console, root, min_size_mb=args.min_size)

    if json_mode:
        dump_json(large_file_scan_payload(results))
        return

    # Display summary
    display_large_file_summary(console, results, args.min_size)

    if not results.files:
        console.print(f"\n[dim]No files larger than {args.min_size}MB found.[/]")
        record_history(
            "files",
            dry_run=dry_run,
            status="empty",
            scanned_count=results.total_files_scanned,
            extra={"found_count": 0},
        )
        return

    # Interactive selection
    files_to_delete = select_files_interactive(
        results.files,
        title=f"Large Files (>{args.min_size}MB)",
    )

    if files_to_delete:
        if confirm_file_deletion(console, files_to_delete, use_trash=use_trash):
            deletion_results = perform_file_deletions(
                console,
                files_to_delete,
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
                f.size for f, success, _ in deletion_results if success and not dry_run
            )
            record_history(
                "files",
                dry_run=dry_run,
                status="completed",
                selected_count=len(files_to_delete),
                deleted_count=sum(1 for _, success, _ in deletion_results if success),
                reclaimed_bytes=reclaimed,
                scanned_count=results.total_files_scanned,
                extra={"found_count": len(results.files)},
            )
        else:
            console.print("\n[yellow]Deletion cancelled.[/]")
            record_history(
                "files",
                dry_run=dry_run,
                status="cancelled",
                selected_count=len(files_to_delete),
                scanned_count=results.total_files_scanned,
                extra={"found_count": len(results.files)},
            )
    else:
        console.print("\n[dim]No files selected for deletion.[/]")
        record_history(
            "files",
            dry_run=dry_run,
            status="no-selection",
            scanned_count=results.total_files_scanned,
            extra={"found_count": len(results.files)},
        )
