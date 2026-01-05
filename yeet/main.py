"""Main entry point for the yeet CLI tool."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

from . import __version__
from .config import get_config
from .scanner import ProjectScanner, LargeFileScanner, CacheScanner, XcodeScanner
from .utils import (
    Project,
    LargeFile,
    CacheLocation,
    XcodeItem,
    ScanResults,
    LargeFileScanResults,
    CacheScanResults,
    XcodeScanResults,
    delete_directory,
    delete_file,
    format_size,
    is_macos,
    move_to_trash,
    trash_available,
)
from .ui.prompts import (
    get_directory_prompt,
    confirm_deletion,
    confirm_continue,
)
from .ui.tables import (
    display_scan_summary,
    display_deletion_results,
    display_cache_scan_summary,
    display_cache_deletion_results,
    display_xcode_scan_summary,
    display_xcode_deletion_results,
)
from .ui.selector import (
    select_projects_interactive,
    select_files_interactive,
    select_caches_interactive,
    select_xcode_items_interactive,
)


def delete_item(path: Path, use_trash: bool) -> tuple[bool, str]:
    """
    Delete a file or directory, optionally using system trash.

    Args:
        path: Path to the file or directory to delete
        use_trash: If True and trash is available, move to trash instead of permanent delete

    Returns:
        Tuple of (success, message)
    """
    if use_trash and trash_available():
        return move_to_trash(path)
    else:
        # Fall back to permanent deletion
        if use_trash and not trash_available():
            # Warn user that trash is not available
            pass  # Warning will be shown elsewhere
        if path.is_dir():
            return delete_directory(path)
        else:
            return delete_file(path)


# ASCII art logo
LOGO = """
                        ██╗   ██╗███████╗███████╗████████╗
                        ╚██╗ ██╔╝██╔════╝██╔════╝╚══██╔══╝
                         ╚████╔╝ █████╗  █████╗     ██║   
                          ╚██╔╝  ██╔══╝  ██╔══╝     ██║   
                           ██║   ███████╗███████╗   ██║   
                           ╚═╝   ╚══════╝╚══════╝   ╚═╝   
"""


def show_welcome(console: Console) -> None:
    """Display the welcome screen with logo."""
    console.print()
    console.print(Text(LOGO, style="bold cyan"))
    console.print(f"  [dim]v{__version__}[/] - [bold]Reclaim your disk space![/]\n")


def show_main_menu(console: Console) -> str:
    """
    Display main menu and get user choice.

    Returns:
        "projects", "files", "caches", "xcode", "explore", or "quit"
    """
    from prompt_toolkit import prompt
    from prompt_toolkit.styles import Style

    console.print()
    console.print("[bold]What would you like to clean up?[/]\n")
    console.print(
        "  [cyan][1][/] [bold]Stale Projects[/]  - Find old coding projects not touched in a while"
    )
    console.print(
        "  [cyan][2][/] [bold]Large Files[/]     - Find big files taking up space"
    )
    console.print(
        "  [cyan][3][/] [bold]System Caches[/]   - Clear browser, package manager, and app caches"
    )
    # Only show Xcode option on macOS
    if is_macos():
        console.print(
            "  [cyan][4][/] [bold]Xcode Cleanup[/]   - Clean device support, simulators, derived data"
        )
    console.print(
        "  [cyan][5][/] [bold]Explore Disk[/]    - Browse directories by size"
    )
    console.print("  [cyan][q][/] [bold]Quit[/]")
    console.print()

    while True:
        try:
            prompt_text = (
                "Enter choice (1/2/3/4/5/q): "
                if is_macos()
                else "Enter choice (1/2/3/5/q): "
            )
            choice = (
                prompt(
                    prompt_text,
                    style=Style.from_dict({"": "cyan bold"}),
                )
                .strip()
                .lower()
            )

            if choice in ("1", "projects", "p"):
                return "projects"
            elif choice in ("2", "files", "f", "large"):
                return "files"
            elif choice in ("3", "caches", "c", "cache"):
                return "caches"
            elif choice in ("4", "xcode", "x") and is_macos():
                return "xcode"
            elif choice in ("5", "explore", "e", "disk"):
                return "explore"
            elif choice in ("q", "quit", "exit", ""):
                return "quit"
            else:
                valid_choices = (
                    "1, 2, 3, 4, 5, or q" if is_macos() else "1, 2, 3, 5, or q"
                )
                console.print(f"[red]Invalid choice. Please enter {valid_choices}[/]")
        except (EOFError, KeyboardInterrupt):
            return "quit"


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

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
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


def run_large_file_scan(
    console: Console,
    root: Path,
    min_size_mb: int = 25,
) -> LargeFileScanResults:
    """Run the large file scan with progress display."""
    scanner = LargeFileScanner(min_size_mb=min_size_mb)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
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


def perform_project_deletions(
    console: Console,
    projects: list[Project],
    use_trash: bool = False,
) -> list[tuple[Project, bool, str]]:
    """Delete selected projects with progress."""
    results: list[tuple[Project, bool, str]] = []

    action_word = "Moving to trash" if use_trash and trash_available() else "Deleting"

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"{action_word}...", total=len(projects))

        for project in projects:
            progress.update(task, description=f"{action_word}: {project.name}")
            success, msg = delete_item(project.path, use_trash)
            results.append((project, success, msg))
            progress.advance(task)

    return results


def perform_file_deletions(
    console: Console,
    files: list[LargeFile],
    use_trash: bool = False,
) -> list[tuple[LargeFile, bool, str]]:
    """Delete selected files with progress."""
    results: list[tuple[LargeFile, bool, str]] = []

    action_word = "Moving to trash" if use_trash and trash_available() else "Deleting"

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"{action_word}...", total=len(files))

        for file in files:
            progress.update(task, description=f"{action_word}: {file.name}")
            success, msg = delete_item(file.path, use_trash)
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
    deleted_files: list[tuple[LargeFile, bool, str]],
    use_trash: bool = False,
) -> None:
    """Display results of file deletion operation."""
    console.print()

    files_success = sum(1 for _, success, _ in deleted_files if success)
    files_failed = len(deleted_files) - files_success

    total_reclaimed = sum(f.size for f, success, _ in deleted_files if success)

    action_noun = "moved to trash" if use_trash else "deleted"
    title_action = "Moved to Trash" if use_trash else "Deletion"

    result_text = (
        f"[bold]{title_action} Complete[/]\n\n"
        f"  Files {action_noun}: [green]{files_success}[/]"
        f"{f' ([red]{files_failed} failed[/])' if files_failed else ''}\n\n"
        f"  [bold green]Space reclaimed: {format_size(total_reclaimed)}[/]"
    )

    if use_trash and files_success > 0:
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
    console: Console, files: list[LargeFile], use_trash: bool = False
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


def handle_stale_projects(console: Console, args: argparse.Namespace) -> None:
    """Handle the stale projects workflow."""
    # Get config for trash setting
    config = get_config()
    use_trash = config.use_trash

    # Check if trash is requested but not available
    if use_trash and not trash_available():
        console.print(
            "[yellow]Warning: Trash not available on this system. "
            "Items will be permanently deleted.[/]"
        )
        use_trash = False

    # Get directory
    if args.directory:
        from .utils import validate_directory

        is_valid, result = validate_directory(args.directory)
        if not is_valid:
            console.print(f"[red]Error:[/] {result}")
            return
        root = result
        args.directory = None
    else:
        root = get_directory_prompt(console)

    # Run scan
    console.print()
    results = run_project_scan(console, root, days_threshold=args.days)

    # Display results
    display_scan_summary(console, results)

    if not results.projects:
        console.print("\n[dim]No stale projects found.[/]")
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
                console, projects_to_delete, use_trash=use_trash
            )
            display_deletion_results(console, deletion_results, use_trash=use_trash)
        else:
            console.print("\n[yellow]Deletion cancelled.[/]")
    else:
        console.print("\n[dim]No projects selected for deletion.[/]")


def handle_large_files(console: Console, args: argparse.Namespace) -> None:
    """Handle the large files workflow."""
    # Get config for trash setting
    config = get_config()
    use_trash = config.use_trash

    # Check if trash is requested but not available
    if use_trash and not trash_available():
        console.print(
            "[yellow]Warning: Trash not available on this system. "
            "Items will be permanently deleted.[/]"
        )
        use_trash = False

    # Get directory
    if args.directory:
        from .utils import validate_directory

        is_valid, result = validate_directory(args.directory)
        if not is_valid:
            console.print(f"[red]Error:[/] {result}")
            return
        root = result
        args.directory = None
    else:
        root = get_directory_prompt(console)

    # Run scan
    console.print()
    results = run_large_file_scan(console, root, min_size_mb=args.min_size)

    # Display summary
    display_large_file_summary(console, results, args.min_size)

    if not results.files:
        console.print(f"\n[dim]No files larger than {args.min_size}MB found.[/]")
        return

    # Interactive selection
    files_to_delete = select_files_interactive(
        results.files,
        title=f"Large Files (>{args.min_size}MB)",
    )

    if files_to_delete:
        if confirm_file_deletion(console, files_to_delete, use_trash=use_trash):
            deletion_results = perform_file_deletions(
                console, files_to_delete, use_trash=use_trash
            )
            display_file_deletion_results(
                console, deletion_results, use_trash=use_trash
            )
        else:
            console.print("\n[yellow]Deletion cancelled.[/]")
    else:
        console.print("\n[dim]No files selected for deletion.[/]")


def run_cache_scan(
    console: Console,
    min_size_mb: int = 1,
) -> CacheScanResults:
    """Run the cache scan with progress display."""
    scanner = CacheScanner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
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
) -> list[tuple[CacheLocation, bool, str]]:
    """Delete selected caches with progress."""
    results: list[tuple[CacheLocation, bool, str]] = []

    action_word = "Moving to trash" if use_trash and trash_available() else "Clearing"

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"{action_word} caches...", total=len(caches))

        for cache in caches:
            progress.update(task, description=f"{action_word}: {cache.name}")
            success, msg = delete_item(cache.path, use_trash)
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
    import platform

    # Get config for trash setting
    config = get_config()
    use_trash = config.use_trash

    # Check if trash is requested but not available
    if use_trash and not trash_available():
        console.print(
            "[yellow]Warning: Trash not available on this system. "
            "Items will be permanently deleted.[/]"
        )
        use_trash = False

    # Show OS info
    os_name = platform.system()
    console.print(f"\n[dim]Detected OS: {os_name}[/]")

    # Run scan
    console.print()
    results = run_cache_scan(console, min_size_mb=args.min_cache_size)

    # Display summary
    display_cache_scan_summary(console, results)

    if not results.caches:
        console.print("\n[dim]No significant caches found.[/]")
        return

    # Interactive selection
    caches_to_clear = select_caches_interactive(
        results.caches,
        title="System Caches (sorted by size)",
    )

    if caches_to_clear:
        if confirm_cache_deletion(console, caches_to_clear, use_trash=use_trash):
            deletion_results = perform_cache_deletions(
                console, caches_to_clear, use_trash=use_trash
            )
            display_cache_deletion_results(
                console, deletion_results, use_trash=use_trash
            )
        else:
            console.print("\n[yellow]Cache cleanup cancelled.[/]")
    else:
        console.print("\n[dim]No caches selected for cleanup.[/]")


def run_xcode_scan(
    console: Console,
) -> XcodeScanResults:
    """Run the Xcode scan with progress display."""
    scanner = XcodeScanner()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
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
) -> list[tuple[XcodeItem, bool, str]]:
    """Delete selected Xcode items with progress."""
    results: list[tuple[XcodeItem, bool, str]] = []
    from .utils import XcodeItemType
    import subprocess

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Cleaning up...", total=len(items))

        for item in items:
            progress.update(task, description=f"Deleting: {item.name}")

            # Simulator runtimes need special handling via simctl
            if item.item_type == XcodeItemType.SIMULATOR_RUNTIME:
                uuid = item.app_info.get("uuid") if item.app_info else None
                if uuid:
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
    if not is_macos():
        console.print("\n[yellow]Xcode cleanup is only available on macOS.[/]")
        return

    console.print("\n[dim]Scanning Xcode data directories...[/]")

    # Run scan
    console.print()
    results = run_xcode_scan(console)

    # Display summary
    display_xcode_scan_summary(console, results)

    if not results.items:
        console.print("\n[dim]No Xcode items found to clean up.[/]")
        return

    # Interactive selection
    items_to_delete = select_xcode_items_interactive(
        results.items,
        title="Xcode Cleanup",
    )

    if items_to_delete:
        if confirm_xcode_deletion(console, items_to_delete):
            deletion_results = perform_xcode_deletions(console, items_to_delete)
            display_xcode_deletion_results(console, deletion_results)
        else:
            console.print("\n[yellow]Xcode cleanup cancelled.[/]")
    else:
        console.print("\n[dim]No items selected for cleanup.[/]")


def handle_disk_explorer(console: Console, args: argparse.Namespace) -> None:
    """Handle the disk explorer workflow."""
    from rich.prompt import Confirm

    from .scanner import DiskExplorer
    from .ui.explorer import DiskExplorerUI

    # Get config for settings
    config = get_config()
    start_path = Path(config.start_path).expanduser()
    use_trash = config.use_trash

    console.print("\n[dim]Starting disk explorer...[/]")

    # Check if trash is requested but not available
    if use_trash and not trash_available():
        console.print(
            "[yellow]Warning: Trash not available on this system. "
            "Items will be permanently deleted.[/]"
        )
        use_trash = False

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

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
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
    from .scanner import DiskExplorer
    from .utils import SIZE_LOADING

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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="yeet",
        description="Find and delete stale projects, large files, and system caches to reclaim disk space.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yeet                       # Interactive mode with menu
  yeet /path/to/scan         # Scan specific directory
  yeet --days 30             # Projects inactive for 30+ days
  yeet --min-size 50         # Files larger than 50MB
  yeet --min-cache-size 10   # Caches larger than 10MB
  yeet ~/Library --export results.json  # Export scan to JSON file
  yeet ~/Downloads --export -           # Export scan to stdout
        """,
    )

    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Directory to scan (default: prompt for directory)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        metavar="DAYS",
        help="Days since last activity to consider project stale (default: 90)",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=25,
        metavar="MB",
        help="Minimum file size in MB to flag as large (default: 25)",
    )
    parser.add_argument(
        "--min-cache-size",
        type=int,
        default=1,
        metavar="MB",
        help="Minimum cache size in MB to show (default: 1)",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--export",
        type=str,
        metavar="FILE",
        help="Export scan results to JSON file (use - for stdout)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    console = Console()

    try:
        # Handle export mode (non-interactive)
        if args.export:
            from .utils import validate_directory

            if not args.directory:
                console.print("[red]Error:[/] --export requires a directory argument")
                console.print("Usage: yeet <directory> --export <output.json>")
                return 1

            is_valid, result = validate_directory(args.directory)
            if not is_valid:
                console.print(f"[red]Error:[/] {result}")
                return 1

            export_disk_scan(result, args.export)
            return 0

        # Show welcome screen
        show_welcome(console)

        while True:
            # Show main menu
            choice = show_main_menu(console)

            if choice == "quit":
                break
            elif choice == "projects":
                handle_stale_projects(console, args)
            elif choice == "files":
                handle_large_files(console, args)
            elif choice == "caches":
                handle_cache_scan(console, args)
            elif choice == "xcode":
                handle_xcode_cleanup(console, args)
            elif choice == "explore":
                handle_disk_explorer(console, args)

            # Ask to continue
            if not confirm_continue(console):
                break

        console.print("\n[bold green]Thanks for using yeet! Stay clean![/] 🚀\n")
        return 0

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted by user.[/]\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
