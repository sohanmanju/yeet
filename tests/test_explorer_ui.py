"""Tests for DiskExplorerUI filtering and info behavior."""

from datetime import datetime

from yeet.scanner import DiskExplorer
from yeet.ui.explorer import DiskExplorerUI
from yeet.ui.explorer_render import get_item_info
from yeet.utils import DiskItem


def test_filter_matches_path(tmp_path):
    explorer = DiskExplorer(min_size_bytes=0)
    ui = DiskExplorerUI(explorer, start_path=tmp_path)

    item = DiskItem(
        path=tmp_path / "Nested" / "cache.bin",
        name="cache.bin",
        size=1024,
        is_dir=False,
        modified=datetime.now(),
    )
    ui.items = [item]
    enter_keys(ui, "fnested\r")
    view = ui.screen_view()
    assert view.count == 1
    assert "cache.bin" in "".join(text for _, text in view.row(0))


def test_info_panel_shows_item_count(tmp_path):
    explorer = DiskExplorer(min_size_bytes=0)
    ui = DiskExplorerUI(explorer, start_path=tmp_path)

    parent = DiskItem(
        path=tmp_path,
        name=tmp_path.name,
        size=3_000,
        is_dir=True,
        modified=datetime.now(),
        item_count=2,
    )
    ui.items = [parent]

    info_text = "".join(fragment[1] for fragment in get_item_info(ui, parent))

    assert "Items: 2" in info_text


def enter_keys(ui, keys):
    from prompt_toolkit import Application
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    from prompt_toolkit.layout import Layout, Window

    bindings = ui.key_bindings()

    @bindings.add("c-x")
    def finish(event):
        event.app.exit()

    with (
        create_pipe_input() as pipe,
        create_app_session(input=pipe, output=DummyOutput()),
    ):
        pipe.send_text(keys + "\x18")
        Application(layout=Layout(Window()), key_bindings=bindings).run()


def test_filter_input_treats_command_keys_as_text(tmp_path, monkeypatch):
    ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), start_path=tmp_path)
    selected = tmp_path / "selected"
    ui.selected = {selected}

    def unexpected(*args, **kwargs):
        raise AssertionError("A command ran while entering filter text")

    monkeypatch.setattr(ui, "navigate_to", unexpected)
    monkeypatch.setattr(ui, "navigate_back", unexpected)
    monkeypatch.setattr(ui, "refresh", unexpected)
    enter_keys(ui, "fdsrt/hq? \r")
    assert ui.filter_text == "dsrt/hq? "
    assert ui.selected == {selected}
    assert ui.sort_mode == "size"
    assert not ui.show_help


def test_age_input_ignores_commands_and_accepts_digits(tmp_path):
    ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), start_path=tmp_path)
    ui.selected = {tmp_path / "selected"}
    enter_keys(ui, "adsrt/hq?123\r")
    assert ui.age_filter_days == 123
    assert ui.selected == {tmp_path / "selected"}
    assert ui.sort_mode == "size"


def test_filtered_items_follow_sort_and_inventory_updates(tmp_path):
    ui = DiskExplorerUI(DiskExplorer(min_size_bytes=0), start_path=tmp_path)
    now = datetime.now()
    ui.items = [
        DiskItem(tmp_path / name, name, size, False, now)
        for name, size in [("cache-b", 10), ("cache-a", 20), ("other", 30)]
    ]
    enter_keys(ui, "fcache\rs")
    view = ui.screen_view()
    assert view.count == 2
    assert "cache-a" in "".join(text for _, text in view.row(0))
    assert "cache-b" in "".join(text for _, text in view.row(1))
    ui.items.pop(0)
    view = ui.screen_view()
    assert view.count == 1
    assert "cache-b" in "".join(text for _, text in view.row(0))
