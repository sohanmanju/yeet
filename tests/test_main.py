"""Tests for yeet.main."""

from io import StringIO
import sys
import json

import pytest

from rich.console import Console

import yeet.main as main
from yeet.main import Workflow, parse_args, show_main_menu


def test_parse_args_supports_json(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yeet", "--json", "--workflow", "caches"])

    args = parse_args()

    assert args.json is True
    assert args.workflow == "caches"


def test_parse_args_supports_purge_workflow(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yeet", "--workflow", "purge"])

    args = parse_args()

    assert args.workflow == "purge"


def test_parse_args_supports_installer_workflow(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yeet", "--workflow", "installer"])

    args = parse_args()

    assert args.workflow == "installer"


def test_parse_args_supports_leftovers_workflow(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yeet", "--workflow", "leftovers"])

    args = parse_args()

    assert args.workflow == "leftovers"


def test_parse_args_supports_history_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yeet", "--history"])

    args = parse_args()

    assert args.history is True


def test_main_menu_selects_workflows_and_the_quit_option(monkeypatch):
    from tests.test_journey import terminal_input

    workflows = [
        Workflow("projects", "Stale Projects", "Find old projects", lambda *_: None),
        Workflow("purge", "Project Artifacts", "Remove build outputs", lambda *_: None),
    ]
    monkeypatch.setattr(main, "WORKFLOWS", workflows)
    console = Console(file=StringIO())
    assert terminal_input("j\r", lambda: show_main_menu(console)) == "purge"
    assert terminal_input("jj\r", lambda: show_main_menu(console)) == "quit"


@pytest.mark.parametrize(
    "workflow_args,to_stdout", [([], True), (["--workflow", "explore"], False)]
)
def test_cli_exports_scanned_files_as_json(
    tmp_path, monkeypatch, capsys, workflow_args, to_stdout
):
    root = tmp_path / "scan"
    root.mkdir()
    (root / "large.txt").write_text("x" * 10000)
    (root / "small.txt").write_text("ab")
    (root / "empty.txt").touch()
    output = tmp_path / "export.json"
    destination = "-" if to_stdout else str(output)
    monkeypatch.setattr(
        sys, "argv", ["yeet", str(root), "--export", destination, *workflow_args]
    )
    assert main.main() == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out if to_stdout else output.read_text())
    assert payload["root_path"] == str(root.resolve())
    assert [item["name"] for item in payload["items"]] == ["large.txt", "small.txt"]


def test_export_rejects_missing_root_and_unrelated_workflows(tmp_path, monkeypatch):
    output = tmp_path / "export.json"
    for arguments in (
        ["--export", str(output)],
        ["--workflow", "files", "--export", str(output)],
    ):
        monkeypatch.setattr(sys, "argv", ["yeet", *arguments])
        assert main.main() == 1
    assert not output.exists()


def test_json_requires_workflow_even_with_export(tmp_path, monkeypatch):
    output = tmp_path / "export.json"
    monkeypatch.setattr(
        sys, "argv", ["yeet", str(tmp_path), "--json", "--export", str(output)]
    )
    assert main.main() == 1
    assert not output.exists()
