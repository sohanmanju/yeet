"""Tests for yeet.main."""

from io import StringIO
import sys

from rich.console import Console

import yeet.main as main
from yeet.main import Workflow, parse_args, show_main_menu


def test_parse_args_supports_json(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yeet", "--json", "--workflow", "caches"])

    args = parse_args()

    assert args.json is True
    assert args.workflow == "caches"
    assert args.dry_run is False


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


def test_show_main_menu_builds_arrow_options(monkeypatch):
    workflows = [
        Workflow("projects", "Stale Projects", "Find old projects", lambda *_: None),
        Workflow("purge", "Project Artifacts", "Remove build outputs", lambda *_: None),
    ]

    captured: dict[str, object] = {}

    class FakeMenu:
        def __init__(self, options, title):
            captured["options"] = options
            captured["title"] = title

        def run(self):
            return "purge"

    monkeypatch.setattr(main, "_available_workflows", lambda: workflows)
    monkeypatch.setattr(main, "WorkflowMenu", FakeMenu)

    choice = show_main_menu(Console(file=StringIO()))

    assert choice == "purge"
    assert captured["title"] == "What would you like to clean up?"
    assert [option.key for option in captured["options"]] == [
        "projects",
        "purge",
        "quit",
    ]
    assert all(not hasattr(option, "shortcut") for option in captured["options"])
