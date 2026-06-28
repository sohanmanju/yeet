"""History view workflow."""

from __future__ import annotations

import argparse

from rich.console import Console

from ..history import read_history, render_history


def handle_history(console: Console, args: argparse.Namespace) -> None:
    """Show operation history."""
    entries = read_history(limit=getattr(args, "limit", None))
    render_history(console, entries)
