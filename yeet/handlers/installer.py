"""Downloaded installer cleanup workflow."""

from ..scanners import InstallerScanner
from ..ui.selector import DeletionItemSelector
from ..json_output import installer_scan_payload
from .session import run_scan_workflow
from .workflow import RootPolicy, ScanBatch, ScanProgress
from pathlib import Path
from ..models import InstallerItem


def handle_installer_cleanup(console, args):
    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[InstallerItem]:
        results = InstallerScanner().scan(root, progress_callback=progress)
        return ScanBatch(
            results.items,
            len(results.items),
            results.scan_errors,
            installer_scan_payload(root, results),
        )

    run_scan_workflow(
        console,
        args,
        key="installer",
        title="Installer Files",
        root_policy=RootPolicy.DEFAULT_LOCATIONS,
        scan=scan,
        selector=DeletionItemSelector,
    )
