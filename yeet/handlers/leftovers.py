"""Unused application data cleanup workflow."""

from ..scanners import LeftoverScanner
from ..ui.selector import DeletionItemSelector
from ..json_output import leftovers_scan_payload
from ..filesystem import is_macos
from .session import run_scan_workflow
from .workflow import RootPolicy, ScanBatch, ScanProgress
from pathlib import Path
from ..models import LeftoverItem


def handle_leftovers_cleanup(console, args):
    if not is_macos():
        console.print("[yellow]Leftovers cleanup is only available on macOS.[/]")
        return

    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[LeftoverItem]:
        results = LeftoverScanner().scan(progress_callback=progress)
        return ScanBatch(
            results.items,
            len(results.items),
            results.scan_errors,
            leftovers_scan_payload(results),
        )

    run_scan_workflow(
        console,
        args,
        key="leftovers",
        title="App Leftovers",
        root_policy=RootPolicy.SYSTEM,
        scan=scan,
        selector=DeletionItemSelector,
    )
