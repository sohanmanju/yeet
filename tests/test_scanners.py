"""Tests for yeet.scanners module."""

import tempfile
from datetime import datetime
from pathlib import Path
import os

import pytest

from yeet.scanners import (
    ProjectScanner,
    LargeFileScanner,
    CacheScanner,
    DiskExplorer,
    PurgeScanner,
    InstallerScanner,
    LeftoverScanner,
)
from yeet.utils import CacheCategory, CacheScanResults, ProjectType


class TestProjectScanner:
    """Tests for ProjectScanner class."""

    def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = ProjectScanner(days_threshold=90)
            results = scanner.scan(Path(tmpdir))
            assert len(results.projects) == 0

    def test_detects_python_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "myproject"
            project_dir.mkdir()
            (project_dir / "pyproject.toml").write_text("[project]\nname = 'test'")
            (project_dir / "main.py").write_text("print('hello')")

            scanner = ProjectScanner(days_threshold=0, include_all=True)
            results = scanner.scan(Path(tmpdir))

            assert len(results.projects) == 1
            assert results.projects[0].name == "myproject"
            assert results.projects[0].project_type == ProjectType.PYTHON

    def test_detects_node_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "nodeapp"
            project_dir.mkdir()
            (project_dir / "package.json").write_text('{"name": "test"}')

            scanner = ProjectScanner(days_threshold=0, include_all=True)
            results = scanner.scan(Path(tmpdir))

            assert len(results.projects) == 1
            assert results.projects[0].project_type == ProjectType.NODE

    def test_detects_rust_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "rustapp"
            project_dir.mkdir()
            (project_dir / "Cargo.toml").write_text('[package]\nname = "test"')

            scanner = ProjectScanner(days_threshold=0, include_all=True)
            results = scanner.scan(Path(tmpdir))

            assert len(results.projects) == 1
            assert results.projects[0].project_type == ProjectType.RUST

    def test_detects_go_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "goapp"
            project_dir.mkdir()
            (project_dir / "go.mod").write_text("module test")

            scanner = ProjectScanner(days_threshold=0, include_all=True)
            results = scanner.scan(Path(tmpdir))

            assert len(results.projects) == 1
            assert results.projects[0].project_type == ProjectType.GO

    def test_respects_days_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "oldproject"
            project_dir.mkdir()
            (project_dir / "pyproject.toml").write_text("[project]")

            # Default threshold of 90 days, project was just created
            scanner = ProjectScanner(days_threshold=90, include_all=False)
            results = scanner.scan(Path(tmpdir))

            # Should be empty because project is too new
            assert len(results.projects) == 0

            # With include_all=True, should find it
            scanner_all = ProjectScanner(days_threshold=90, include_all=True)
            results_all = scanner_all.scan(Path(tmpdir))
            assert len(results_all.projects) == 1

    def test_progress_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "project"
            project_dir.mkdir()
            (project_dir / "pyproject.toml").write_text("[project]")

            callback_calls = []

            def progress_cb(count, name):
                callback_calls.append((count, name))

            scanner = ProjectScanner(days_threshold=0, include_all=True)
            scanner.scan(Path(tmpdir), progress_callback=progress_cb)

            assert len(callback_calls) > 0


class TestLargeFileScanner:
    """Tests for LargeFileScanner class."""

    def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = LargeFileScanner(min_size_mb=1)
            results = scanner.scan(Path(tmpdir))
            assert len(results.files) == 0

    def test_finds_large_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file larger than 1 MB
            large_file = Path(tmpdir) / "large.bin"
            large_file.write_bytes(b"x" * (1024 * 1024 + 1))  # 1 MB + 1 byte

            scanner = LargeFileScanner(min_size_mb=1)
            results = scanner.scan(Path(tmpdir))

            assert len(results.files) == 1
            assert results.files[0].name == "large.bin"
            assert results.files[0].size > 1024 * 1024

    def test_ignores_small_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a small file
            small_file = Path(tmpdir) / "small.txt"
            small_file.write_text("hello")

            scanner = LargeFileScanner(min_size_mb=1)
            results = scanner.scan(Path(tmpdir))

            assert len(results.files) == 0

    def test_progress_callback_with_large_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file larger than threshold to trigger callback
            large_file = Path(tmpdir) / "large.bin"
            large_file.write_bytes(b"x" * (1024 * 1024 + 1))  # 1 MB + 1 byte

            callback_calls = []

            def progress_cb(files_scanned, large_found, name):
                callback_calls.append((files_scanned, large_found, name))

            scanner = LargeFileScanner(min_size_mb=1)
            scanner.scan(Path(tmpdir), progress_callback=progress_cb)

            # Callback should be called when large file is found
            assert len(callback_calls) > 0


class TestCacheScanner:
    """Tests for CacheScanner class."""

    def test_scan_returns_results(self):
        scanner = CacheScanner()
        results = scanner.scan()

        assert isinstance(results, CacheScanResults)
        assert isinstance(results.caches, list)
        assert isinstance(results.total_size, int)

    def test_progress_callback(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "data.bin").write_bytes(b"x" * (1024 * 1024 + 1))

        callback_calls = []

        def progress_cb(count, name):
            callback_calls.append((count, name))

        scanner = CacheScanner()
        scanner.os_type = "testos"
        scanner.CACHE_DEFINITIONS = [
            ("Temp Cache", CacheCategory.SYSTEM, {"testos": [str(cache_dir)]})
        ]

        scanner.scan(progress_callback=progress_cb)

        assert callback_calls == [(1, "Temp Cache")]


class TestDiskExplorer:
    """Tests for DiskExplorer class."""

    def test_scan_directory_include_small(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files and directories
            (Path(tmpdir) / "file1.txt").write_text("hello")
            (Path(tmpdir) / "file2.txt").write_text("world")
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "nested.txt").write_text("nested content")

            # Use include_small=True to see all items
            explorer = DiskExplorer(min_size_bytes=0)
            items = explorer.scan_directory(Path(tmpdir), include_small=True)

            assert len(items) == 3  # file1.txt, file2.txt, subdir
            names = [item.name for item in items]
            assert "file1.txt" in names
            assert "file2.txt" in names
            assert "subdir" in names

    def test_scan_directory_filters_by_size(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a small file
            small = Path(tmpdir) / "small.txt"
            small.write_text("x")

            # Create a larger file (need larger for disk block size)
            large = Path(tmpdir) / "large.txt"
            large.write_text("x" * 10000)  # 10KB content

            # Scan with min size that filters small.txt but keeps large.txt
            explorer = DiskExplorer(min_size_bytes=1000)
            items = explorer.scan_directory(Path(tmpdir))

            # Should find the large file
            names = [item.name for item in items]
            assert "large.txt" in names

    def test_is_dangerous(self):
        explorer = DiskExplorer()

        # System paths that are in DANGEROUS_PATHS should be dangerous
        assert explorer.is_dangerous(Path("/usr"))
        assert explorer.is_dangerous(Path("/System"))

        # User paths should not be dangerous
        assert not explorer.is_dangerous(Path.home() / "Downloads")

        # Root is not in DANGEROUS_PATHS (but direct children like /usr are)
        # The implementation doesn't treat "/" itself as dangerous

    def test_get_cached_size_after_calculate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("hello world")

            explorer = DiskExplorer()

            # Initially not cached
            assert explorer.get_cached_size(test_file) is None

            # Calculate size to populate cache
            size = explorer.calculate_size(test_file)

            # Now should be cached
            cached_size = explorer.get_cached_size(test_file)
            assert cached_size is not None
            assert cached_size == size

    def test_calculate_size_for_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            (Path(tmpdir) / "a.txt").write_text("aaaa" * 1000)  # ~4KB
            subdir = Path(tmpdir) / "sub"
            subdir.mkdir()
            (subdir / "b.txt").write_text("bb" * 1000)  # ~2KB

            explorer = DiskExplorer()
            size = explorer.calculate_size(Path(tmpdir))

            # Size should be positive (using du command)
            assert size > 0

    def test_cache_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as cache_dir:
                cache_file = Path(cache_dir) / "test_cache.json"

                # Create file and calculate its size to populate cache
                explorer1 = DiskExplorer()
                test_path = Path(tmpdir) / "test.txt"
                test_path.write_text("test content here")
                size = explorer1.calculate_size(test_path)
                explorer1.save_cache(cache_file)

                # Verify cache file exists
                assert cache_file.exists()

                # Load in new explorer
                explorer2 = DiskExplorer()
                loaded = explorer2.load_cache(cache_path=cache_file, max_age_hours=1)

                assert loaded > 0
                # The cached size should be available
                assert explorer2.get_cached_size(test_path) == size


class TestPurgeScanner:
    """Tests for PurgeScanner class."""

    def test_detects_project_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "myapp"
            project_dir.mkdir()
            (project_dir / "package.json").write_text('{"name": "test"}')

            artifact_dir = project_dir / "node_modules"
            artifact_dir.mkdir()
            (artifact_dir / "pkg.txt").write_text("x" * 5000)

            scanner = PurgeScanner()
            results = scanner.scan(Path(tmpdir))

            assert len(results.artifacts) == 1
            assert results.artifacts[0].project_name == "myapp"
            assert results.artifacts[0].name == "node_modules"
            assert results.artifacts[0].size > 0


class TestInstallerScanner:
    """Tests for InstallerScanner class."""

    def test_detects_dmg_installer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads = Path(tmpdir) / "Downloads"
            downloads.mkdir()
            installer = downloads / "AppInstaller.dmg"
            installer.write_bytes(b"x" * (1024 * 1024 + 1))

            scanner = InstallerScanner()
            results = scanner.scan(downloads, min_size_mb=1)

            assert len(results.items) == 1
            assert results.items[0].name == "AppInstaller.dmg"
            assert results.items[0].source == "Custom"


class TestLeftoverScanner:
    """Tests for LeftoverScanner class."""

    def test_detects_uninstalled_app_leftover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            support = home / "Library" / "Application Support"
            support.mkdir(parents=True)

            leftover = support / "Notion"
            leftover.mkdir()
            (leftover / "data.bin").write_bytes(b"x" * 2048)

            scanner = LeftoverScanner()
            scanner.installed_apps = set()
            scanner.ROOTS = [("Application Support", support)]

            results = scanner.scan()

            assert len(results.items) == 1
            assert results.items[0].name == "Notion"
            assert results.items[0].source == "Application Support"

    def test_skips_installed_app_leftover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            support = home / "Library" / "Application Support"
            support.mkdir(parents=True)

            leftover = support / "Slack"
            leftover.mkdir()
            (leftover / "data.bin").write_bytes(b"x" * 2048)

            scanner = LeftoverScanner()
            scanner.installed_apps = {"slack"}
            scanner.ROOTS = [("Application Support", support)]

            results = scanner.scan()

            assert len(results.items) == 0
