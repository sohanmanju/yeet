"""Tests for yeet.utils module."""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import os

import pytest

from yeet.utils import (
    format_size,
    format_days_ago,
    validate_directory,
    parse_xcode_version,
    is_macos,
    Project,
    ProjectType,
    LargeFile,
    ScanResults,
    LargeFileScanResults,
    delete_file,
    delete_directory,
)


class TestFormatSize:
    """Tests for format_size function."""

    def test_bytes(self):
        assert format_size(0) == "0 B"
        assert format_size(1) == "1 B"
        assert format_size(512) == "512 B"
        assert format_size(1023) == "1023 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"
        assert format_size(10240) == "10.0 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(1024 * 1024 * 50) == "50.0 MB"
        assert format_size(1024 * 1024 * 512) == "512.0 MB"

    def test_gigabytes(self):
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert format_size(1024 * 1024 * 1024 * 2.5) == "2.5 GB"

    def test_terabytes(self):
        assert format_size(1024 * 1024 * 1024 * 1024) == "1.0 TB"

    def test_negative_returns_zero(self):
        assert format_size(-1) == "0 B"
        assert format_size(-1000) == "0 B"


class TestFormatDaysAgo:
    """Tests for format_days_ago function."""

    def test_none(self):
        assert format_days_ago(None) == "Never"

    def test_today(self):
        assert format_days_ago(0) == "Today"

    def test_yesterday(self):
        assert format_days_ago(1) == "Yesterday"

    def test_days(self):
        assert format_days_ago(2) == "2 days ago"
        assert format_days_ago(7) == "7 days ago"
        assert format_days_ago(29) == "29 days ago"

    def test_months(self):
        assert format_days_ago(30) == "1 month ago"
        assert format_days_ago(60) == "2 months ago"
        assert format_days_ago(364) == "12 months ago"

    def test_years(self):
        assert format_days_ago(365) == "1 year ago"
        assert format_days_ago(730) == "2 years ago"
        assert format_days_ago(1000) == "2 years ago"


class TestValidateDirectory:
    """Tests for validate_directory function."""

    def test_valid_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            is_valid, result = validate_directory(tmpdir)
            assert is_valid is True
            assert result == Path(tmpdir).resolve()

    def test_nonexistent_path(self):
        is_valid, result = validate_directory("/nonexistent/path/12345")
        assert is_valid is False
        assert "does not exist" in result

    def test_file_instead_of_directory(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            try:
                is_valid, result = validate_directory(f.name)
                assert is_valid is False
                assert "not a directory" in result
            finally:
                os.unlink(f.name)

    def test_expands_home(self):
        is_valid, result = validate_directory("~")
        assert is_valid is True
        assert result == Path.home()


class TestParseXcodeVersion:
    """Tests for parse_xcode_version function."""

    def test_simple_version(self):
        version, build = parse_xcode_version("17.0")
        assert version == (17, 0)
        assert build is None

    def test_version_with_build(self):
        version, build = parse_xcode_version("17.0.1 (21B91)")
        assert version == (17, 0, 1)
        assert build == "21B91"

    def test_version_with_arch(self):
        version, build = parse_xcode_version("17.0 (21A329) arm64e")
        assert version == (17, 0)
        assert build == "21A329"

    def test_invalid_version(self):
        version, build = parse_xcode_version("invalid")
        assert version is None
        assert build is None


class TestIsMacos:
    """Tests for is_macos function."""

    @pytest.mark.parametrize(
        "system,expected",
        [("Darwin", True), ("Linux", False), ("Windows", False), ("FreeBSD", False)],
    )
    def test_detects_macos(self, monkeypatch, system, expected):
        monkeypatch.setattr("yeet.filesystem.platform.system", lambda: system)
        assert is_macos() is expected


class TestProject:
    """Tests for Project dataclass."""

    def test_days_stale_uses_most_recent(self):
        now = datetime.now()

        project = Project(
            path=Path("/test"),
            name="test",
            project_type=ProjectType.OTHER,
            total_size=1000,
            last_modified=now - timedelta(days=10),
            last_accessed=now - timedelta(days=20),
            last_commit_date=now - timedelta(days=30),
            is_git_repo=True,
        )
        assert project.days_stale == 10

        project2 = Project(
            path=Path("/test"),
            name="test",
            project_type=ProjectType.OTHER,
            total_size=1000,
            last_modified=now - timedelta(days=30),
            last_accessed=now - timedelta(days=5),
            last_commit_date=now - timedelta(days=20),
            is_git_repo=True,
        )
        assert project2.days_stale == 5

        project3 = Project(
            path=Path("/test"),
            name="test",
            project_type=ProjectType.OTHER,
            total_size=1000,
            last_modified=now - timedelta(days=30),
            last_accessed=now - timedelta(days=20),
            last_commit_date=now - timedelta(days=2),
            is_git_repo=True,
        )
        assert project3.days_stale == 2

    def test_size_formatted(self):
        project = Project(
            path=Path("/test"),
            name="test",
            project_type=ProjectType.OTHER,
            total_size=1024 * 1024 * 100,
            last_modified=datetime.now(),
            last_accessed=datetime.now(),
        )
        assert project.size_formatted == "100.0 MB"

    def test_activity_type(self):
        now = datetime.now()

        project = Project(
            path=Path("/test"),
            name="test",
            project_type=ProjectType.OTHER,
            total_size=1000,
            last_modified=now - timedelta(days=30),
            last_accessed=now - timedelta(days=5),
            last_commit_date=None,
            is_git_repo=False,
        )
        assert project.activity_type == "opened"


class TestLargeFile:
    """Tests for LargeFile dataclass."""

    def test_size_formatted(self):
        f = LargeFile(
            path=Path("/test/file.zip"),
            name="file.zip",
            size=1024 * 1024 * 500,
            last_accessed=datetime.now(),
            last_modified=datetime.now(),
        )
        assert f.size_formatted == "500.0 MB"

    def test_extension(self):
        f = LargeFile(
            path=Path("/test/file.zip"),
            name="file.zip",
            size=1000,
            last_accessed=datetime.now(),
            last_modified=datetime.now(),
        )
        assert f.extension == ".zip"

    def test_extension_no_ext(self):
        f = LargeFile(
            path=Path("/test/noext"),
            name="noext",
            size=1000,
            last_accessed=datetime.now(),
            last_modified=datetime.now(),
        )
        assert f.extension == "—"


class TestScanResults:
    """Tests for ScanResults dataclass."""

    def test_total_reclaimable_size(self):
        now = datetime.now()
        results = ScanResults(
            projects=[
                Project(
                    path=Path("/test1"),
                    name="test1",
                    project_type=ProjectType.OTHER,
                    total_size=100,
                    last_modified=now,
                    last_accessed=now,
                ),
                Project(
                    path=Path("/test2"),
                    name="test2",
                    project_type=ProjectType.OTHER,
                    total_size=200,
                    last_modified=now,
                    last_accessed=now,
                ),
            ]
        )
        assert results.total_reclaimable_size == 300


class TestLargeFileScanResults:
    """Tests for LargeFileScanResults dataclass."""

    def test_total_size(self):
        now = datetime.now()
        results = LargeFileScanResults(
            files=[
                LargeFile(Path("/a"), "a", 100, now, now),
                LargeFile(Path("/b"), "b", 200, now, now),
            ]
        )
        assert results.total_size == 300


class TestDeleteFile:
    """Tests for delete_file function."""

    def test_delete_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)

        assert path.exists()
        success, msg = delete_file(path)
        assert success is True
        assert not path.exists()

    def test_delete_nonexistent_file(self):
        path = Path("/nonexistent/file/12345.txt")
        success, msg = delete_file(path)
        assert success is False
        assert "Not a file" in msg

    def test_delete_directory_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            success, msg = delete_file(Path(tmpdir))
            assert success is False
            assert "Not a file" in msg


class TestDeleteDirectory:
    """Tests for delete_directory function."""

    def test_delete_existing_directory(self):
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir)

        (path / "file1.txt").write_text("test")
        (path / "subdir").mkdir()
        (path / "subdir" / "file2.txt").write_text("test")

        assert path.exists()
        success, msg = delete_directory(path)
        assert success is True
        assert not path.exists()

    def test_delete_nonexistent_directory(self):
        path = Path("/nonexistent/dir/12345")
        success, msg = delete_directory(path)
        assert success is False
        assert "Not a directory" in msg

    def test_delete_file_fails(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)

        try:
            success, msg = delete_directory(path)
            assert success is False
            assert "Not a directory" in msg
        finally:
            path.unlink()
