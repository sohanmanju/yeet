"""Tests for JSON output helpers."""

from datetime import datetime
from pathlib import Path

from yeet.json_output import (
    project_scan_payload,
    disk_scan_payload,
    purge_scan_payload,
    installer_scan_payload,
    leftovers_scan_payload,
)
from yeet.utils import (
    Project,
    ProjectType,
    DiskItem,
    PurgeArtifact,
    PurgeScanResults,
    InstallerItem,
    InstallerScanResults,
    LeftoverItem,
    LeftoverScanResults,
)


def test_project_scan_payload_serializes_projects():
    now = datetime.now()
    results = type(
        "Results",
        (),
        {
            "projects": [
                Project(
                    path=Path("/tmp/app"),
                    name="app",
                    project_type=ProjectType.NODE,
                    total_size=123,
                    last_modified=now,
                    last_accessed=now,
                    is_git_repo=False,
                )
            ],
            "total_projects_scanned": 1,
            "total_size_scanned": 123,
            "total_reclaimable_size": 123,
            "scan_errors": [],
        },
    )()

    payload = project_scan_payload(results)

    assert payload["total_projects_scanned"] == 1
    assert payload["projects"][0]["name"] == "app"
    assert payload["projects"][0]["project_type"] == "node"


def test_disk_scan_payload_serializes_items():
    now = datetime.now()
    items = [
        DiskItem(
            path=Path("/tmp/file.txt"),
            name="file.txt",
            size=4096,
            is_dir=False,
            modified=now,
        )
    ]

    payload = disk_scan_payload(Path("/tmp"), items, 4096)

    assert payload["root_path"] == "/tmp"
    assert payload["items"][0]["name"] == "file.txt"
    assert payload["items"][0]["is_dir"] is False


def test_purge_scan_payload_serializes_artifacts():
    now = datetime.now()
    results = PurgeScanResults(
        artifacts=[
            PurgeArtifact(
                path=Path("/tmp/myapp/node_modules"),
                name="node_modules",
                project_root=Path("/tmp/myapp"),
                project_name="myapp",
                artifact_type="node",
                size=2048,
                last_modified=now,
            )
        ]
    )

    payload = purge_scan_payload(Path("/tmp"), results)

    assert payload["root_path"] == "/tmp"
    assert payload["artifacts"][0]["project_name"] == "myapp"
    assert payload["artifacts"][0]["artifact_type"] == "node"


def test_installer_scan_payload_serializes_items():
    now = datetime.now()
    results = InstallerScanResults(
        items=[
            InstallerItem(
                path=Path("/tmp/AppInstaller.dmg"),
                name="AppInstaller.dmg",
                source="Downloads",
                size=1024,
                last_modified=now,
                extension=".dmg",
            )
        ]
    )

    payload = installer_scan_payload(Path("/tmp"), results)

    assert payload["items"][0]["source"] == "Downloads"
    assert payload["items"][0]["extension"] == ".dmg"


def test_leftovers_scan_payload_serializes_items():
    now = datetime.now()
    results = LeftoverScanResults(
        items=[
            LeftoverItem(
                path=Path("/tmp/Library/Application Support/Notion"),
                name="Notion",
                source="Application Support",
                size=2048,
                last_modified=now,
                app_hint="Notion",
            )
        ]
    )

    payload = leftovers_scan_payload(results)

    assert payload["items"][0]["source"] == "Application Support"
    assert payload["items"][0]["app_hint"] == "Notion"
