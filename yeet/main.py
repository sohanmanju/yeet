"""Main entry point for the yeet CLI tool."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable

from rich.console import Console
from rich.text import Text

from . import __version__
from .utils import is_macos
from .ui.prompts import confirm_continue
from .handlers import (
    handle_stale_projects,
    handle_large_files,
    handle_cache_scan,
    handle_purge,
    handle_installer_cleanup,
    handle_leftovers_cleanup,
    handle_xcode_cleanup,
    handle_disk_explorer,
    handle_history,
    export_disk_scan,
)


# ASCII art logo
LOGO = """
                        ██╗   ██╗███████╗███████╗████████╗
                        ╚██╗ ██╔╝██╔════╝██╔════╝╚══██╔══╝
                         ╚████╔╝ █████╗  █████╗     ██║   
                          ╚██╔╝  ██╔══╝  ██╔══╝     ██║   
                           ██║   ███████╗███████╗   ██║   
                           ╚═╝   ╚══════╝╚══════╝   ╚═╝   
"""


@dataclass(frozen=True)
class Workflow:
    key: str
    label: str
    description: str
    handler: Callable[[Console, argparse.Namespace], None]
    macos_only: bool = False
    aliases: tuple[str, ...] = ()


WORKFLOWS: list[Workflow] = [
    Workflow(
        "projects",
        "Stale Projects",
        "Find old coding projects not touched in a while",
        handle_stale_projects,
        aliases=("p",),
    ),
    Workflow(
        "files",
        "Large Files",
        "Find big files taking up space",
        handle_large_files,
        aliases=("f", "large"),
    ),
    Workflow(
        "caches",
        "System Caches",
        "Clear browser, package manager, and app caches",
        handle_cache_scan,
        aliases=("c", "cache"),
    ),
    Workflow(
        "purge",
        "Project Artifacts",
        "Remove build outputs and dependency caches",
        handle_purge,
        aliases=("artifacts",),
    ),
    Workflow(
        "installer",
        "Installer Cleanup",
        "Remove downloaded installers",
        handle_installer_cleanup,
        aliases=("i", "installers"),
    ),
    Workflow(
        "leftovers",
        "App Leftovers",
        "Clean data from uninstalled apps",
        handle_leftovers_cleanup,
        macos_only=True,
        aliases=("l",),
    ),
    Workflow(
        "xcode",
        "Xcode Cleanup",
        "Clean device support, simulators, derived data",
        handle_xcode_cleanup,
        macos_only=True,
        aliases=("x",),
    ),
    Workflow(
        "explore", "Explore Disk", "Browse directories by size", handle_disk_explorer
    ),
    Workflow(
        "history", "History", "Review past cleanup runs", handle_history, aliases=("h",)
    ),
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
    """Display the welcome screen with logo."""
    console.print()
    console.print(Text(LOGO, style="bold cyan"))
    console.print(f"  [dim]v{__version__}[/] - [bold]Reclaim your disk space![/]\n")


def show_main_menu(console: Console) -> str:
    """
    Display main menu and get user choice.

    Returns:
        "projects", "files", "caches", "purge", "installer", "leftovers", "xcode", "explore", "history", or "quit"
    """
    from prompt_toolkit import prompt
    from prompt_toolkit.styles import Style

    workflows = _available_workflows()
    choice_map = {
        str(idx): workflow.key for idx, workflow in enumerate(workflows, start=1)
    }
    choice_map.update({workflow.key: workflow.key for workflow in workflows})
    choice_map.update(
        {alias: workflow.key for workflow in workflows for alias in workflow.aliases}
    )
    choice_map.update({"q": "quit", "quit": "quit", "exit": "quit", "": "quit"})

    console.print()
    console.print("[bold]What would you like to clean up?[/]\n")
    for idx, workflow in enumerate(workflows, start=1):
        console.print(
            f"  [cyan][{idx}][/] [bold]{workflow.label}[/]  - {workflow.description}"
        )
    console.print("  [cyan][q][/] [bold]Quit[/]")
    console.print()

    while True:
        try:
            prompt_text = f"Enter choice ({'/'.join(str(i) for i in range(1, len(workflows) + 1))}/q): "
            choice = (
                prompt(
                    prompt_text,
                    style=Style.from_dict({"": "cyan bold"}),
                )
                .strip()
                .lower()
            )

            selected = choice_map.get(choice)
            if selected is not None:
                return selected
            else:
                valid_choices = f"1 through {len(workflows)}, or q"
                console.print(f"[red]Invalid choice. Please enter {valid_choices}[/]")
        except (EOFError, KeyboardInterrupt):
            return "quit"


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
        "--dry-run",
        action="store_true",
        help="Preview deletions without modifying anything",
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
        help="Limit rows shown in history view (default: 25)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    console = Console()

    try:
        if args.history and not args.workflow:
            args.workflow = "history"

        if args.workflow:
            if args.export and args.workflow != "explore":
                console.print(
                    "[red]Error:[/] --export is only supported with --workflow explore"
                )
                return 1

            if args.workflow == "explore" and args.export:
                from .utils import validate_directory

                if not args.directory:
                    console.print(
                        "[red]Error:[/] --export requires a directory argument"
                    )
                    console.print("Usage: yeet <directory> --export <output.json>")
                    return 1

                is_valid, result = validate_directory(args.directory)
                if not is_valid:
                    console.print(f"[red]Error:[/] {result}")
                    return 1

                export_disk_scan(result, args.export)
                return 0

            _dispatch_workflow(console, args, args.workflow)
            return 0

        if args.json:
            console.print(
                "[red]Error:[/] --json requires --workflow to select a workflow"
            )
            return 1

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
            else:
                _dispatch_workflow(console, args, choice)

            # Ask to continue
            if not confirm_continue(console):
                break

        console.print("\n[bold green]Thanks for using yeet! Stay clean![/] \n")
        return 0

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted by user.[/]\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
