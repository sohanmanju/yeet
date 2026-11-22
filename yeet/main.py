"""Main entry point for the yeet CLI tool."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console

from . import __version__
from .config import Config
from .handlers import (
    export_disk_scan,
    handle_cache_scan,
    handle_disk_explorer,
    handle_history,
    handle_installer_cleanup,
    handle_large_files,
    handle_leftovers_cleanup,
    handle_purge,
    handle_stale_projects,
    handle_xcode_cleanup,
)
from .ui.menu import WorkflowMenu, build_workflow_menu_options
from .filesystem import is_macos, validate_directory


@dataclass(frozen=True)
class Workflow:
    key: str
    label: str
    description: str
    handler: Callable[[Console, argparse.Namespace], None]
    macos_only: bool = False


WORKFLOWS: list[Workflow] = [
    Workflow(
        "projects",
        "Stale Projects",
        "Find old coding projects not touched in a while",
        handle_stale_projects,
    ),
    Workflow(
        "files",
        "Large Files",
        "Find big files taking up space",
        handle_large_files,
    ),
    Workflow(
        "caches",
        "System Caches",
        "Clear browser, package manager, and app caches",
        handle_cache_scan,
    ),
    Workflow(
        "purge",
        "Project Artifacts",
        "Remove build outputs and dependency caches",
        handle_purge,
    ),
    Workflow(
        "installer",
        "Installer Cleanup",
        "Remove downloaded installers",
        handle_installer_cleanup,
    ),
    Workflow(
        "leftovers",
        "App Leftovers",
        "Clean data from uninstalled apps",
        handle_leftovers_cleanup,
        macos_only=True,
    ),
    Workflow(
        "xcode",
        "Xcode Cleanup",
        "Clean device support, simulators, derived data",
        handle_xcode_cleanup,
        macos_only=True,
    ),
    Workflow(
        "explore", "Explore Disk", "Browse directories by size", handle_disk_explorer
    ),
    Workflow("history", "History", "Review past cleanup runs", handle_history),
]


def _available_workflows() -> list[Workflow]:
    return [workflow for workflow in WORKFLOWS if not workflow.macos_only or is_macos()]


def _workflow_by_key(key: str) -> Workflow | None:
    for workflow in WORKFLOWS:
        if workflow.key == key:
            return workflow
    return None


def _dispatch_workflow(console: Console, args: argparse.Namespace, key: str) -> None:
    workflow = _workflow_by_key(key)
    if workflow is None:
        console.print(f"[red]Error:[/] Unknown workflow: {key}")
        return
    workflow.handler(console, args)


def show_welcome(console: Console) -> None:
    """Display a compact welcome line before entering the full-screen UI."""
    console.print(f"  [bold]yeet[/] [dim]v{__version__} · Reclaim your disk space[/]")


def show_main_menu(console: Console) -> str:
    """Display the arrow-navigable main menu and return the selected workflow."""
    workflows = _available_workflows()
    menu_options = build_workflow_menu_options(
        (workflow.key, workflow.label, workflow.description) for workflow in workflows
    )
    menu = WorkflowMenu(menu_options, title="What would you like to clean up?")
    return menu.run()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    defaults = Config()
    parser = argparse.ArgumentParser(
        prog="yeet",
        description="Find and delete stale projects, large files, and system caches to reclaim disk space.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yeet                       # Interactive mode with menu
  yeet /path/to/scan         # Scan specific directory
  yeet --workflow caches --json  # JSON output for a workflow
  yeet --workflow purge      # Clean project artifacts
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
        default=defaults.days_threshold,
        metavar="DAYS",
        help="Days since last activity to consider project stale (default: %(default)s)",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=defaults.large_file_mb,
        metavar="MB",
        help="Minimum file size in MB to flag as large (default: %(default)s)",
    )
    parser.add_argument(
        "--min-cache-size",
        type=int,
        default=defaults.cache_size_mb,
        metavar="MB",
        help="Minimum cache size in MB to show (default: %(default)s)",
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print scan results as JSON and exit",
    )
    parser.add_argument(
        "--workflow",
        choices=[workflow.key for workflow in WORKFLOWS],
        help="Run a specific workflow without showing the menu",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Show cleanup history and exit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Limit rows shown in history view (default: %(default)s)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    console = Console()

    try:
        if args.history and not args.workflow:
            args.workflow = "history"

        if args.json and not args.workflow:
            console.print(
                "[red]Error:[/] --json requires --workflow to select a workflow"
            )
            return 1

        if args.export and args.workflow not in (None, "explore"):
            console.print(
                "[red]Error:[/] --export is only supported with --workflow explore"
            )
            return 1

        if args.export:
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

        if args.workflow:
            _dispatch_workflow(console, args, args.workflow)
            if args.json or args.workflow == "history":
                return 0
            args.workflow = None
            args.directory = None

        show_welcome(console)

        while True:
            choice = show_main_menu(console)

            if choice == "quit":
                break
            _dispatch_workflow(console, args, choice)

        console.print("\n[bold green]Thanks for using yeet! Stay clean![/] \n")
        return 0

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted by user.[/]\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
