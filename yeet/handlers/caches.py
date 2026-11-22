"""System cache cleanup, including caches whose parent must be retained."""

from ..config import get_config
from ..scanners import CacheScanner
from ..safety import is_protected_path
from ..ui.selector import CacheSelector
from ..json_output import cache_scan_payload
from .common import delete_item
from .session import run_scan_workflow
from .workflow import RootPolicy, ScanBatch, ScanProgress
from pathlib import Path
from ..models import CacheLocation


def _delete_cache_contents(path, *, use_trash, config):
    if is_protected_path(path, config):
        return False, f"Protected path: {path}"
    if not path.exists():
        return True, f"Cache directory missing, skipped: {path}"
    if not path.is_dir():
        return delete_item(path, use_trash, config=config)
    failures = []
    for child in sorted(path.iterdir()):
        success, message = delete_item(child, use_trash, config=config)
        if not success:
            failures.append(message)
    return (
        (False, "; ".join(failures))
        if failures
        else (True, f"Cleared contents: {path}; parent retained")
    )


def delete_cache(cache, use_trash, config):
    if cache.delete_contents_only and cache.path.is_dir():
        return _delete_cache_contents(cache.path, use_trash=use_trash, config=config)
    return delete_item(cache.path, use_trash, config=config)


def handle_cache_scan(console, args):
    config = get_config()

    def scan(root: Path | None, progress: ScanProgress) -> ScanBatch[CacheLocation]:
        results = CacheScanner().scan(
            progress_callback=progress, min_size_mb=args.min_cache_size
        )
        return ScanBatch(
            results.caches,
            len(results.caches),
            results.scan_errors,
            cache_scan_payload(results),
            review_notes={
                item.path: "Clears contents; keeps the parent directory."
                for item in results.caches
                if item.delete_contents_only
            },
        )

    run_scan_workflow(
        console,
        args,
        key="caches",
        title="System Caches",
        root_policy=RootPolicy.SYSTEM,
        scan=scan,
        selector=CacheSelector,
        delete=lambda item, use_trash: delete_cache(item, use_trash, config),
    )
