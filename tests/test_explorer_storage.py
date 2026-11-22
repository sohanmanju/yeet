"""Folder meters retain category identity and report real scan progress."""

from datetime import datetime

from yeet.scanner import DiskExplorer
from yeet.ui import explorer_render
from yeet.ui.explorer import DiskExplorerUI
from yeet.utils import SIZE_LOADING, DiskItem


def item(root, name, size, directory=False):
    return DiskItem(root / name, name, size, directory, datetime.now())


def snapshot(ui, monkeypatch):
    captured = {}

    def meter(segments, total, **kwargs):
        captured.update(segments=segments, total=total, **kwargs)
        return []

    monkeypatch.setattr(explorer_render, "dot_meter", meter)
    captured["text"] = "".join(
        text for _, text in explorer_render.get_storage_overview(ui)
    )
    return captured


def test_photos_share_a_stable_category_not_a_color_per_file(tmp_path, monkeypatch):
    ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), tmp_path)
    ui.items = [item(tmp_path, f"photo-{i}.jpg", i + 1) for i in range(8)]
    first = snapshot(ui, monkeypatch)
    assert [(s.label, s.size) for s in first["segments"]] == [("Photos", 36)]
    ui.items.append(item(tmp_path, "movie.mov", 100))
    second = snapshot(ui, monkeypatch)
    assert (
        next(s.color for s in second["segments"] if s.label == "Photos")
        == first["segments"][0].color
    )


def test_unknown_total_uses_explicit_item_progress_not_a_full_byte_bar(
    tmp_path, monkeypatch
):
    ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), tmp_path)
    ui.items = [
        item(tmp_path, "photo.jpg", 25),
        item(tmp_path, "pending", SIZE_LOADING, True),
    ]
    partial = snapshot(ui, monkeypatch)
    assert "1/2 items measured" in partial["text"]
    assert sum(s.size for s in partial["segments"]) < partial["total"]
    ui.items[1].size = 75
    complete = snapshot(ui, monkeypatch)
    assert sum(s.size for s in complete["segments"]) == complete["total"]


def test_small_photos_are_in_inventory_even_when_hidden_from_list(tmp_path):
    for i in range(4):
        (tmp_path / f"photo-{i}.jpg").write_bytes(b"image")
    ui = DiskExplorerUI(DiskExplorer(), tmp_path)
    ui._scan_current_directory()
    assert "Photos" in "".join(
        text for _, text in explorer_render.get_storage_overview(ui)
    )
    hidden = ui.screen_view()
    assert "No visible items" in "".join(text for _, text in hidden.row(0))
    ui.show_small_items = True
    assert ui.screen_view().count == 4


def test_file_enumeration_publishes_partial_batches(tmp_path):
    for i in range(140):
        (tmp_path / f"photo-{i}.jpg").write_bytes(b"image")
    updates = []
    explorer = DiskExplorer(min_size_bytes=0)
    result = explorer.scan_directory(
        tmp_path,
        include_small=True,
        on_update=lambda items, pending: updates.append((len(items), pending)),
    )
    assert len(result) == 140
    assert any(0 < count < 140 and pending > 0 for count, pending in updates)
    assert updates[-1] == (140, 0)


def test_directory_batches_do_not_block_keys_and_stale_results_are_discarded(
    tmp_path, monkeypatch
):
    import asyncio
    import threading
    from io import StringIO

    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.data_structures import Size
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.output.vt100 import Vt100_Output

    from yeet.ui.application import TerminalApplication
    from yeet.ui.view import ViewLayout

    async def scenario():
        release = threading.Event()
        callbacks = {}
        ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), tmp_path)

        def read(path, include_small, *, on_update, stop_event):
            callbacks[path] = on_update
            on_update([item(path, "photo.jpg", 25)], 1)
            release.wait(3)
            return []

        monkeypatch.setattr(ui.explorer, "scan_directory", read)
        output = Vt100_Output(
            StringIO(), lambda: Size(rows=24, columns=80), enable_cpr=False
        )
        with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
            keys = KeyBindings()

            @keys.add("q")
            def quit(event):
                event.app.exit()

            app = TerminalApplication(
                layout=ViewLayout(ui.screen_view).layout,
                input=pipe,
                output=output,
                key_bindings=keys,
            )
            ui._app = app
            app.pre_run_callables.append(ui._scan_current_directory)
            task = asyncio.create_task(app.run_async())

            async def until(predicate):
                for _ in range(200):
                    if predicate():
                        return
                    await asyncio.sleep(0.005)
                raise AssertionError("Directory batch was not presented")

            try:
                await until(lambda: ui.listing and len(ui.items) == 1)
                old_path = ui.current_path
                ui.current_path = tmp_path / "next"
                ui._scan_current_directory()
                await until(
                    lambda: ui.items and ui.items[0].path.parent == ui.current_path
                )
                # Simulate a late completion from an already cancelled worker.
                callbacks[old_path]([item(old_path, "stale.mov", 999)], 0)
                await asyncio.sleep(0.02)
                assert ui.items[0].name == "photo.jpg"
                assert ui.items[0].path.parent == ui.current_path
                pipe.send_text("q")
                await asyncio.wait_for(task, 1)
            finally:
                ui._stop_loading.set()
                release.set()
                if not task.done():
                    app.exit()
                    await task
                ui._app = None

    asyncio.run(scenario())


def test_painting_visible_rows_does_not_rewalk_inventory_for_each_row(tmp_path):
    class Inventory(list):
        visited = 0

        def __iter__(self):
            for item in super().__iter__():
                self.visited += 1
                yield item

    ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), tmp_path)
    ui.items = Inventory(item(tmp_path, f"photo-{i}.jpg", 10) for i in range(1000))
    view = ui.screen_view()
    ui.items.visited = 0
    for i in range(30):
        assert "photo-" in "".join(text for _, text in view.row(i))
    assert ui.items.visited <= 1000
