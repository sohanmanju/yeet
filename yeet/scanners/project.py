"""Project scanner for finding stale coding projects."""

from __future__ import annotations

import os
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import (
    DAYS_SINCE_ACCESS,
    SKIP_FOR_SIZE,
    Project,
    ProjectType,
    ScanResults,
)


class ProjectScanner:
    """
    Scans for coding projects and analyzes their staleness.

    A project is identified by the presence of common project markers
    like package.json, pyproject.toml, Cargo.toml, .git, etc.

    Projects are treated as atomic units - we show project-level info,
    not individual files within projects.
    """

    def __init__(
        self,
        days_threshold: int = DAYS_SINCE_ACCESS,
        include_all: bool = False,
    ) -> None:
        """
        Args:
            days_threshold: Only include projects not modified in this many days
            include_all: If True, include all projects regardless of age
        """
        self.days_threshold = days_threshold
        self.include_all = include_all
        self._git_available = self._check_git_available()

    @staticmethod
    def _check_git_available() -> bool:
        """Check if git command is available."""
        try:
            subprocess.run(
                ["git", "--version"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def scan(
        self,
        root: Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> ScanResults:
        """
        Scan for coding projects under root directory.

        Args:
            root: Root directory to search
            progress_callback: Optional callback(projects_found, current_dir)

        Returns:
            ScanResults containing all found projects
        """
        results = ScanResults()

        # BFS to find project directories
        dirs_to_scan: deque[Path] = deque([root])

        while dirs_to_scan:
            current_dir = dirs_to_scan.popleft()

            try:
                # Check if this directory is a project
                project_type = self._detect_project_type(current_dir)

                if project_type is not None:
                    # This is a project - analyze it
                    project = self._analyze_project(current_dir, project_type)

                    if project:
                        results.total_projects_scanned += 1
                        results.total_size_scanned += project.total_size

                        # Apply threshold filter
                        if (
                            self.include_all
                            or project.days_stale >= self.days_threshold
                        ):
                            results.projects.append(project)

                        if progress_callback:
                            progress_callback(
                                results.total_projects_scanned, current_dir.name
                            )

                    # Don't recurse into project directories
                    # (nested projects will be found when we scan subdirs that aren't projects)
                    continue

                # Not a project - scan subdirectories
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                name = entry.name
                                # Skip hidden dirs and known heavy directories
                                if (
                                    not name.startswith(".")
                                    and name not in SKIP_FOR_SIZE
                                ):
                                    dirs_to_scan.append(Path(entry.path))
                        except (OSError, PermissionError):
                            continue

            except (OSError, PermissionError) as e:
                results.scan_errors.append(f"{current_dir}: {e}")
                continue

        return results

    def _detect_project_type(self, path: Path) -> ProjectType | None:
        """
        Detect if directory is a coding project and return its type.

        Returns None if not a project.
        """
        try:
            entries = set()
            with os.scandir(path) as it:
                for entry in it:
                    entries.add(entry.name)

            # Check for git first (most common)
            if ".git" in entries:
                # Further classify by other markers
                if "package.json" in entries:
                    return ProjectType.NODE
                if (
                    "pyproject.toml" in entries
                    or "setup.py" in entries
                    or "requirements.txt" in entries
                ):
                    return ProjectType.PYTHON
                if "Cargo.toml" in entries:
                    return ProjectType.RUST
                if "go.mod" in entries:
                    return ProjectType.GO
                return ProjectType.GIT

            # Check for non-git projects
            if "package.json" in entries:
                return ProjectType.NODE
            if "pyproject.toml" in entries or "setup.py" in entries:
                return ProjectType.PYTHON
            if "Cargo.toml" in entries:
                return ProjectType.RUST
            if "go.mod" in entries:
                return ProjectType.GO
            if "Gemfile" in entries:
                return ProjectType.OTHER
            if "pom.xml" in entries or "build.gradle" in entries:
                return ProjectType.OTHER
            if "composer.json" in entries:
                return ProjectType.OTHER
            if "pubspec.yaml" in entries:
                return ProjectType.OTHER

            # Check for Xcode projects
            for name in entries:
                if name.endswith(".xcodeproj") or name.endswith(".xcworkspace"):
                    return ProjectType.OTHER

            return None

        except (OSError, PermissionError):
            return None

    def _analyze_project(self, path: Path, project_type: ProjectType) -> Project | None:
        """Analyze a project directory and extract metadata."""
        try:
            is_git = (path / ".git").is_dir()

            # Get last commit date if git repo
            last_commit = None
            if is_git:
                last_commit = self._get_last_commit_date(path)

            total_size, last_modified, last_accessed = self._get_project_stats(path)

            return Project(
                path=path,
                name=path.name,
                project_type=project_type,
                total_size=total_size,
                last_modified=last_modified,
                last_accessed=last_accessed,
                last_commit_date=last_commit,
                is_git_repo=is_git,
            )
        except Exception:
            return None

    def _get_project_stats(self, path: Path) -> tuple[int, datetime, datetime]:
        """Calculate project size and latest access times in one traversal."""
        total = 0
        stat = path.stat()
        latest_mtime = stat.st_mtime
        latest_atime = stat.st_atime

        try:
            stack = [path]
            while stack:
                current = stack.pop()
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                fstat = entry.stat(follow_symlinks=False)
                                total += fstat.st_size
                                if fstat.st_mtime > latest_mtime:
                                    latest_mtime = fstat.st_mtime
                                if fstat.st_atime > latest_atime:
                                    latest_atime = fstat.st_atime
                            elif entry.is_dir(follow_symlinks=False):
                                name = entry.name
                                if name not in SKIP_FOR_SIZE and not name.startswith(
                                    "."
                                ):
                                    stack.append(Path(entry.path))
                        except (OSError, PermissionError):
                            continue
        except (OSError, PermissionError):
            pass

        return (
            total,
            datetime.fromtimestamp(latest_mtime),
            datetime.fromtimestamp(latest_atime),
        )

    def _get_last_commit_date(self, project_path: Path) -> datetime | None:
        """Get the date of the last commit in a git repository."""
        if self._git_available:
            try:
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%ct"],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0 and result.stdout.strip():
                    timestamp = int(result.stdout.strip())
                    return datetime.fromtimestamp(timestamp)
            except (subprocess.SubprocessError, ValueError, OSError):
                pass

        # Fallback: check .git file timestamps
        return self._get_last_commit_via_files(project_path)

    def _get_last_commit_via_files(self, project_path: Path) -> datetime | None:
        """Estimate last commit date from .git file modification times."""
        git_dir = project_path / ".git"

        files_to_check = [
            git_dir / "index",
            git_dir / "HEAD",
            git_dir / "COMMIT_EDITMSG",
            git_dir / "logs" / "HEAD",
        ]

        latest_mtime: float | None = None

        for file_path in files_to_check:
            try:
                if file_path.exists():
                    mtime = file_path.stat().st_mtime
                    if latest_mtime is None or mtime > latest_mtime:
                        latest_mtime = mtime
            except (OSError, PermissionError):
                continue

        if latest_mtime:
            return datetime.fromtimestamp(latest_mtime)

        return None
