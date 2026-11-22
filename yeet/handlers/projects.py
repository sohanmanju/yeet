"""Stale project workflow."""

from ..scanners import ProjectScanner
from ..ui.selector import InteractiveSelector
from ..json_output import project_scan_payload
from .session import run_scan_workflow
from .workflow import ScanBatch, ScanProgress
from pathlib import Path
from ..models import Project


def handle_stale_projects(console, args):
    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[Project]:
        assert root is not None, "Directory workflows require a root"
        results = ProjectScanner(days_threshold=args.days, include_all=False).scan(
            root, progress_callback=progress
        )
        return ScanBatch(
            sorted(results.projects, key=lambda item: item.days_stale, reverse=True),
            results.total_projects_scanned,
            results.scan_errors,
            project_scan_payload(results),
        )

    run_scan_workflow(
        console,
        args,
        key="projects",
        title=f"Stale Projects (>{args.days} days inactive)",
        scan=scan,
        selector=InteractiveSelector,
    )
