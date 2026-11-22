"""Xcode cleanup; simulator runtimes require simctl rather than filesystem removal."""

import subprocess

from ..config import get_config
from ..scanners import XcodeScanner
from ..safety import is_protected_path
from ..ui.selector import XcodeSelector
from ..json_output import xcode_scan_payload
from ..models import XcodeItemType
from ..filesystem import is_macos
from .common import delete_item
from .session import run_scan_workflow
from .workflow import RootPolicy, ScanBatch, ScanProgress
from pathlib import Path
from ..models import XcodeItem


def delete_xcode_item(item, config):
    if is_protected_path(item.path, config):
        return False, f"Protected path: {item.path}"
    if item.item_type != XcodeItemType.SIMULATOR_RUNTIME:
        return delete_item(item.path, False, config=config)
    uuid = item.app_info.get("uuid") if item.app_info else None
    if not uuid:
        return False, "No UUID found for runtime"
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "runtime", "delete", uuid],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return (
            (True, f"Deleted runtime: {item.name}")
            if result.returncode == 0
            else (False, result.stderr.strip() or "Failed to delete runtime")
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"Failed to run simctl: {error}"


def handle_xcode_cleanup(console, args):
    if not is_macos():
        console.print("[yellow]Xcode cleanup is only available on macOS.[/]")
        return
    config = get_config()

    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[XcodeItem]:
        results = XcodeScanner().scan(progress_callback=progress)
        return ScanBatch(
            results.items,
            len(results.items),
            results.scan_errors,
            xcode_scan_payload(results),
        )

    run_scan_workflow(
        console,
        args,
        key="xcode",
        title="Xcode Cleanup",
        root_policy=RootPolicy.SYSTEM,
        permanent=True,
        scan=scan,
        selector=XcodeSelector,
        delete=lambda item, use_trash: delete_xcode_item(item, config),
    )
