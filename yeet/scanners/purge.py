"""Scanner for project artifact cleanup."""

from __future__ import annotations

import os
import subprocess
import shutil
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

from ..utils import PROJECT_MARKERS, PurgeArtifact, PurgeScanResults


class PurgeScanner:
    """Scan project trees for generated artifacts like node_modules and build dirs."""

    ARTIFACT_TYPES = {
        "node_modules": "node",
        "dist": "build",
        "build": "build",
        "target": "rust",
        ".next": "next",
        ".nuxt": "nuxt",
        ".venv": "python",
        "venv": "python",
        ".gradle": "gradle",
        ".build": "swift",
        "Pods": "cocoapods",
        "DerivedData": "xcode",
    }

    def __init__(self) -> None:
        self._du_available = self._check_du_available()

    @staticmethod
    def _check_du_available() -> bool:
        return shutil.which("du") is not None

    def scan(
        self,
        root: Path,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> PurgeScanResults:
        results = PurgeScanResults()
        seen: set[Path] = set()
        scanned = 0

        for current_root, dirs, _ in os.walk(root):
            current_path = Path(current_root)
            for dirname in list(dirs):
                if dirname not in self.ARTIFACT_TYPES:
                    continue

                artifact_path = current_path / dirname
                if artifact_path in seen:
                    continue

                seen.add(artifact_path)
                dirs.remove(dirname)
                scanned += 1

                try:
                    size = self._get_size(artifact_path)
                    mtime = datetime.fromtimestamp(artifact_path.stat().st_mtime)
                    project_root = self._find_project_root(artifact_path, root)
                    artifact = PurgeArtifact(
                        path=artifact_path,
                        name=artifact_path.name,
                        project_root=project_root,
                        project_name=project_root.name,
                        artifact_type=self.ARTIFACT_TYPES[dirname],
                        size=size,
                        last_modified=mtime,
                    )
                    results.artifacts.append(artifact)
                    if progress_callback:
                        progress_callback(scanned, artifact_path.name)
                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{artifact_path}: {e}")

        results.artifacts.sort(key=lambda artifact: artifact.size, reverse=True)
        return results

    def _get_size(self, path: Path) -> int:
        if not self._du_available:
            return self._fallback_size(path)

        try:
            proc = subprocess.run(
                ["du", "-sk", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = proc.stdout.strip()
            if output:
                return int(output.split()[0]) * 1024
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
        return self._fallback_size(path)

    def _fallback_size(self, path: Path) -> int:
        total = 0
        try:
            for root, _, files in os.walk(path):
                for name in files:
                    try:
                        total += (Path(root) / name).stat().st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total

    def _find_project_root(self, path: Path, root: Path) -> Path:
        current = path.parent
        while True:
            if self._looks_like_project(current):
                return current
            if current == root or current.parent == current:
                break
            current = current.parent
        return path.parent

    def _looks_like_project(self, path: Path) -> bool:
        try:
            entries = {entry.name for entry in os.scandir(path)}
        except (OSError, PermissionError):
            return False

        for marker in PROJECT_MARKERS:
            for entry in entries:
                if fnmatch(entry, marker):
                    return True
        return False
