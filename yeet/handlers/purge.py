"""Project artifact cleanup workflow."""

from ..scanners import PurgeScanner
from ..ui.selector import DeletionItemSelector
from ..json_output import purge_scan_payload
from .session import run_scan_workflow
from .workflow import ScanBatch, ScanProgress
from pathlib import Path
from ..models import PurgeArtifact


def handle_purge(console, args):
    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[PurgeArtifact]:
        assert root is not None, "Directory workflows require a root"
        results = PurgeScanner().scan(root, progress_callback=progress)
        return ScanBatch(
            results.artifacts,
            len(results.artifacts),
            results.scan_errors,
            purge_scan_payload(root, results),
        )

    run_scan_workflow(
        console,
        args,
        key="purge",
        title="Project Artifacts",
        scan=scan,
        selector=DeletionItemSelector,
    )
