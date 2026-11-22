"""Large file workflow."""

from ..scanners import LargeFileScanner
from ..ui.selector import DeletionItemSelector
from ..json_output import large_file_scan_payload
from .session import run_scan_workflow
from .workflow import ScanBatch, ScanProgress
from pathlib import Path
from ..models import LargeFile


def handle_large_files(console, args):
    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[LargeFile]:
        assert root is not None, "Directory workflows require a root"
        results = LargeFileScanner(min_size_mb=args.min_size).scan(
            root, progress_callback=progress
        )
        return ScanBatch(
            results.files,
            results.total_files_scanned,
            results.scan_errors,
            large_file_scan_payload(results),
        )

    run_scan_workflow(
        console,
        args,
        key="files",
        title=f"Large Files (>{args.min_size} MB)",
        scan=scan,
        selector=DeletionItemSelector,
    )
