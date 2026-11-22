"""Terminal presentation of cleanup history."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from ..formatting import format_size


def render_history(console: Console, entries: list[dict]) -> None:
    """Render history entries in a rich table."""
    console.print()

    if not entries:
        console.print(Panel("[dim]No history found.[/]", title="Yeet History"))
        return

    table = Table(title="Yeet History", box=box.ROUNDED, header_style="bold magenta")
    table.add_column("Time", style="cyan", no_wrap=True)
    table.add_column("Workflow", style="bold")
    table.add_column("Status", style="yellow")
    table.add_column("Selected", justify="right")
    table.add_column("Deleted", justify="right")
    table.add_column("Reclaimed", justify="right")

    for entry in entries:
        timestamp = str(entry.get("timestamp", ""))
        if "T" in timestamp:
            timestamp = (
                timestamp.split("T", 1)[0] + " " + timestamp.split("T", 1)[1][:8]
            )
        table.add_row(
            timestamp,
            str(entry.get("workflow", "")),
            str(entry.get("status", "")),
            str(entry.get("selected_count", 0)),
            str(entry.get("deleted_count", 0)),
            format_size(int(entry.get("reclaimed_bytes", 0))),
        )

    console.print(table)
