"""Shared scan → select → review → cleanup → results navigation."""

from __future__ import annotations

from pathlib import Path
from argparse import Namespace
from collections.abc import Callable

from rich.console import Console

from ..config import get_config
from ..json_output import dump_json
from ..ui.journey import (
    BusyScreen,
    JourneyPage,
    ResultsScreen,
    ReviewItem,
    ReviewScreen,
    choose_directory,
)
from ..filesystem import trash_available, validate_directory
from ..ui.selection import SelectionEngine
from ..ui.selection_model import SelectionState
from .workflow import RootPolicy, ScanBatch, ScanProgress, T
from .common import delete_item, execute_items, record_history, record_cleanup


def run_scan_workflow(
    console: Console,
    args: Namespace,
    *,
    key: str,
    title: str,
    scan: Callable[[Path | None, ScanProgress], ScanBatch[T]],
    selector: Callable[[list[T], str], SelectionEngine[T]],
    root_policy: RootPolicy = RootPolicy.DIRECTORY,
    delete: Callable[[T, bool], tuple[bool, str]] | None = None,
    permanent: bool = False,
) -> None:
    """Own navigation while scanners and operation adapters own filesystem semantics.

    System-wide workflows rescan their fixed locations; directory workflows keep
    the current mode when choosing a new root. JSON runs never open terminal UI.
    """
    config = get_config()
    directory = root_policy.accepts_directory
    root = (
        None
        if root_policy is not RootPolicy.DIRECTORY
        else Path(config.start_path).expanduser()
    )
    supplied = args.directory
    if supplied and directory:
        valid, value = validate_directory(supplied)
        if not valid:
            if args.json:
                console.print(f"[red]Error:[/] {value}")
                return
            root = choose_directory(Path(config.start_path).expanduser())
            if root is None:
                return
        else:
            root = value
    elif root_policy is RootPolicy.DIRECTORY and not args.json:
        root = choose_directory(root)
        if root is None:
            return

    if args.json:
        batch = scan(root, lambda *_: None)
        dump_json(batch.payload)
        return

    if delete is None:

        def delete(item, use_trash):
            return delete_item(item.path, use_trash, config=config)

    failed_items: dict[Path, T] = {}
    selection = SelectionState()
    while True:
        context = str(root) if root is not None else "System locations"

        def perform_scan(update):
            def progress(count: int, detail: str | int, name: str = "") -> None:
                parts = (count, detail, name) if name else (count, detail)
                update(" · ".join(map(str, parts)))

            return scan(root, progress)

        batch = BusyScreen("Scanning · " + title, context).run(perform_scan)
        found = list(batch.items)
        present = {item.path for item in found}
        found.extend(item for path, item in failed_items.items() if path not in present)
        scanned = batch.scanned_count
        error_message = (
            f"{len(batch.errors)} scan errors; some locations were inaccessible."
            if batch.errors
            else ""
        )
        if not found:
            record_history(key, status="empty", scanned_count=scanned)
            actions = [("continue", "Scan again")]
            if directory:
                actions.append(("directory", "Choose another directory"))
            actions.append(("menu", "Main menu"))
            result_page = JourneyPage(
                title,
                context,
                "No matching items found",
                [],
                actions,
                note=error_message,
            )
        else:
            ui = selector(found, title)
            ui.restore_selection(selection)
            ui.status_message = error_message
            while True:
                selected = ui.run()
                if ui.cancelled:
                    return
                if not selected:
                    ui.status_message = "Select one or more items to review · Space selects · q returns to menu"
                    continue
                unavailable = (
                    not permanent and config.use_trash and not trash_available()
                )
                use_trash = not permanent and config.use_trash and not unavailable
                review = ReviewScreen(
                    [
                        ReviewItem(
                            item.path, item.size, batch.review_notes.get(item.path, "")
                        )
                        for item in selected
                    ],
                    use_trash,
                    context,
                    trash_unavailable=unavailable,
                )
                if review.within(ui).run() != "confirm":
                    record_history(
                        key,
                        status="cancelled",
                        selected_count=len(selected),
                        scanned_count=scanned,
                    )
                    continue
                operation = "Moving to Trash" if use_trash else "Permanently deleting"
                outcomes = (
                    BusyScreen(operation, context)
                    .within(ui)
                    .run(
                        lambda update: execute_items(
                            selected, use_trash, delete, update
                        )
                    )
                )
                record_cleanup(key, outcomes, use_trash, scanned_count=scanned)
                failed_items = {item.path: item for item, ok, _ in outcomes if not ok}
                previous = ui.selection_state()
                selection = SelectionState(
                    frozenset(failed_items), previous.focused_path, previous.position
                )
                rows = [
                    (ReviewItem(item.path, item.size), ok, msg)
                    for item, ok, msg in outcomes
                ]
                result_page = ResultsScreen(
                    rows, use_trash, context, directory=directory
                ).within(ui)
                break
        while True:
            choice = result_page.run()
            if choice in ("back", "menu"):
                return
            if choice != "directory":
                break
            selected_root = choose_directory(
                root or Path(config.start_path).expanduser()
            )
            if selected_root is not None:
                root = selected_root
                failed_items.clear()
                selection = SelectionState()
                break
