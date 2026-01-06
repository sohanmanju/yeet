"""Main entry point for the yeet CLI tool."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

from . import __version__
from .utils import is_macos
from .ui.prompts import confirm_continue
from .handlers import (
    handle_stale_projects,
    handle_large_files,
    handle_cache_scan,
    handle_xcode_cleanup,
    handle_disk_explorer,
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

        console.print("\n[bold green]Thanks for using yeet! Stay clean![/] \n")
        return 0

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted by user.[/]\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
