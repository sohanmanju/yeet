"""Workflow adapters normalize scanner contracts before entering navigation."""

from argparse import Namespace
from io import StringIO
import json

import pytest
from rich.console import Console

from yeet.config import Config
from yeet.handlers import session
from yeet.handlers.workflow import RootPolicy, ScanBatch


@pytest.mark.parametrize("policy", list(RootPolicy))
@pytest.mark.parametrize("supplied", [False, True])
def test_json_root_policies_are_explicit_and_do_not_open_ui(
    tmp_path, monkeypatch, capsys, policy, supplied
):
    configured = tmp_path / "configured"
    supplied_root = tmp_path / "supplied"
    configured.mkdir()
    supplied_root.mkdir()
    monkeypatch.setattr(
        session, "get_config", lambda: Config(start_path=str(configured))
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("JSON scanning opened terminal UI")

    monkeypatch.setattr(session, "choose_directory", unexpected)
    monkeypatch.setattr(session.BusyScreen, "run", unexpected)
    roots = []

    def scan(root, progress):
        roots.append(root)
        return ScanBatch([], 12, ["inaccessible"], {"root": str(root), "scanned": 12})

    session.run_scan_workflow(
        Console(file=StringIO()),
        Namespace(directory=str(supplied_root) if supplied else None, json=True),
        key="test",
        title="Test",
        scan=scan,
        selector=unexpected,
        root_policy=policy,
    )
    expected = None
    if policy is RootPolicy.DIRECTORY:
        expected = supplied_root.resolve() if supplied else configured
    elif policy is RootPolicy.DEFAULT_LOCATIONS and supplied:
        expected = supplied_root.resolve()
    assert roots == [expected]
    assert json.loads(capsys.readouterr().out) == {"root": str(expected), "scanned": 12}


@pytest.mark.parametrize(
    "module_name,handler_name,scanner_name,result_name",
    [
        ("files", "handle_large_files", "LargeFileScanner", "LargeFileScanResults"),
        ("projects", "handle_stale_projects", "ProjectScanner", "ScanResults"),
        ("purge", "handle_purge", "PurgeScanner", "PurgeScanResults"),
        (
            "installer",
            "handle_installer_cleanup",
            "InstallerScanner",
            "InstallerScanResults",
        ),
        ("caches", "handle_cache_scan", "CacheScanner", "CacheScanResults"),
        (
            "leftovers",
            "handle_leftovers_cleanup",
            "LeftoverScanner",
            "LeftoverScanResults",
        ),
        ("xcode", "handle_xcode_cleanup", "XcodeScanner", "XcodeScanResults"),
    ],
)
def test_every_workflow_adapter_preserves_scan_errors_in_json(
    tmp_path, monkeypatch, capsys, module_name, handler_name, scanner_name, result_name
):
    import importlib
    from yeet import models

    module = importlib.import_module("yeet.handlers." + module_name)

    class Scanner:
        def __init__(self, **kwargs):
            pass

        def scan(self, *args, **kwargs):
            return getattr(models, result_name)(scan_errors=["permission denied"])

    monkeypatch.setattr(module, scanner_name, Scanner)
    if module_name in ("leftovers", "xcode"):
        monkeypatch.setattr(module, "is_macos", lambda: True)
    args = Namespace(
        directory=str(tmp_path), json=True, days=90, min_size=25, min_cache_size=1
    )
    getattr(module, handler_name)(Console(file=StringIO()), args)
    assert json.loads(capsys.readouterr().out)["scan_errors"] == ["permission denied"]
