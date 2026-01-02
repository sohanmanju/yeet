"""Main entry point for the yeet CLI tool."""

from __future__ import annotations

import argparse
import sys
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
from .scanner import ProjectScanner, LargeFileScanner, CacheScanner
from .utils import (
    Project,
    LargeFile,
    CacheLocation,
    ScanResults,
    LargeFileScanResults,
    CacheScanResults,
    delete_directory,
    delete_file,
    format_size,
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
)
from .ui.selector import (
    select_projects_interactive,
    select_files_interactive,
    select_caches_interactive,
)
from .ui.spacemap import SpaceItem, display_treemap


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
        "projects", "files", "caches", or "quit"
    """
    from prompt_toolkit import prompt
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import FormattedText
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
    console.print("  [cyan][q][/] [bold]Quit[/]")
    console.print()

    while True:
        try:
            choice = (
                prompt(
                    "Enter choice (1/2/3/q): ",
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
            elif choice in ("q", "quit", "exit", ""):
                return "quit"
            else:
                console.print("[red]Invalid choice. Please enter 1, 2, 3, or q[/]")
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
) -> list[tuple[Project, bool, str]]:
    """Delete selected projects with progress."""
    results: list[tuple[Project, bool, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Deleting...", total=len(projects))

        for project in projects:
            progress.update(task, description=f"Deleting: {project.name}")
            success, msg = delete_directory(project.path)
            results.append((project, success, msg))
            progress.advance(task)

    return results


def perform_file_deletions(
    console: Console,
    files: list[LargeFile],
) -> list[tuple[LargeFile, bool, str]]:
    """Delete selected files with progress."""
    results: list[tuple[LargeFile, bool, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Deleting...", total=len(files))

        for file in files:
            progress.update(task, description=f"Deleting: {file.name}")
            success, msg = delete_file(file.path)
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
) -> None:
    """Display results of file deletion operation."""
    console.print()

    files_success = sum(1 for _, success, _ in deleted_files if success)
    files_failed = len(deleted_files) - files_success

    total_reclaimed = sum(f.size for f, success, _ in deleted_files if success)

    console.print(
        Panel(
            f"[bold]Deletion Complete[/]\n\n"
            f"  Files deleted: [green]{files_success}[/]"
            f"{f' ([red]{files_failed} failed[/])' if files_failed else ''}\n\n"
            f"  [bold green]Space reclaimed: {format_size(total_reclaimed)}[/]",
            title="Deletion Summary",
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


def confirm_file_deletion(console: Console, files: list[LargeFile]) -> bool:
    """Show summary and confirm file deletion."""
    from rich.prompt import Confirm

    total_size = sum(f.size for f in files)

    console.print()
    console.print(
        Panel(
            f"[bold red]About to delete {len(files)} file(s):[/]\n\n"
            + "\n".join(f"  - {f.name} ({f.size_formatted})" for f in files[:10])
            + (f"\n  ... and {len(files) - 10} more" if len(files) > 10 else "")
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]",
            title="Deletion Summary",
            border_style="red",
        )
    )
    console.print()

    return Confirm.ask(
        "[bold red]Are you sure you want to delete these files?[/]",
        default=False,
        console=console,
    )


def handle_stale_projects(console: Console, args: argparse.Namespace) -> None:
    """Handle the stale projects workflow."""
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

    # Display space map
    space_items = [
        SpaceItem(name=p.name, size=p.total_size, category=p.project_type.value)
        for p in results.projects
    ]
    display_treemap(console, space_items, title="Space by Project")

    # Sort and select
    sorted_projects = sorted(results.projects, key=lambda p: p.days_stale, reverse=True)

    projects_to_delete = select_projects_interactive(
        sorted_projects,
        title=f"Stale Projects (>{args.days} days inactive)",
    )

    if projects_to_delete:
        if confirm_deletion(console, projects_to_delete):
            deletion_results = perform_project_deletions(console, projects_to_delete)
            display_deletion_results(console, deletion_results)
        else:
            console.print("\n[yellow]Deletion cancelled.[/]")
    else:
        console.print("\n[dim]No projects selected for deletion.[/]")


def handle_large_files(console: Console, args: argparse.Namespace) -> None:
    """Handle the large files workflow."""
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

    # Display space map
    space_items = [
        SpaceItem(name=f.name, size=f.size, category=f.extension) for f in results.files
    ]
    display_treemap(console, space_items, title="Space by File")

    # Interactive selection
    files_to_delete = select_files_interactive(
        results.files,
        title=f"Large Files (>{args.min_size}MB)",
    )

    if files_to_delete:
        if confirm_file_deletion(console, files_to_delete):
            deletion_results = perform_file_deletions(console, files_to_delete)
            display_file_deletion_results(console, deletion_results)
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
) -> list[tuple[CacheLocation, bool, str]]:
    """Delete selected caches with progress."""
    results: list[tuple[CacheLocation, bool, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Clearing caches...", total=len(caches))

        for cache in caches:
            progress.update(task, description=f"Clearing: {cache.name}")
            success, msg = delete_directory(cache.path)
            results.append((cache, success, msg))
            progress.advance(task)

    return results


def confirm_cache_deletion(console: Console, caches: list[CacheLocation]) -> bool:
    """Show summary and confirm cache deletion."""
    from rich.prompt import Confirm

    total_size = sum(c.size for c in caches)

    console.print()
    console.print(
        Panel(
            f"[bold red]About to clear {len(caches)} cache(s):[/]\n\n"
            + "\n".join(f"  - {c.name} ({c.size_formatted})" for c in caches[:10])
            + (f"\n  ... and {len(caches) - 10} more" if len(caches) > 10 else "")
            + f"\n\n[bold]Total space to reclaim:[/] [green]{format_size(total_size)}[/]\n\n"
            + "[dim]Note: Some caches will be recreated as you use apps.[/]",
            title="Cache Cleanup",
            border_style="red",
        )
    )
    console.print()

    return Confirm.ask(
        "[bold red]Are you sure you want to clear these caches?[/]",
        default=False,
        console=console,
    )


def handle_cache_scan(console: Console, args: argparse.Namespace) -> None:
    """Handle the cache scan workflow."""
    import platform

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

    # Display space map by category
    space_items = [
        SpaceItem(name=c.name, size=c.size, category=c.category.value)
        for c in results.caches
    ]
    display_treemap(console, space_items, title="Space by Cache")

    # Interactive selection
    caches_to_clear = select_caches_interactive(
        results.caches,
        title="System Caches (sorted by size)",
    )

    if caches_to_clear:
        if confirm_cache_deletion(console, caches_to_clear):
            deletion_results = perform_cache_deletions(console, caches_to_clear)
            display_cache_deletion_results(console, deletion_results)
        else:
            console.print("\n[yellow]Cache cleanup cancelled.[/]")
    else:
        console.print("\n[dim]No caches selected for cleanup.[/]")


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

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    console = Console()

    try:
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
