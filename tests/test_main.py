"""Tests for yeet.main."""

import sys

from yeet.main import parse_args


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
