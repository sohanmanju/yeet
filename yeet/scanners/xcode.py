"""Xcode scanner for finding Xcode-related data that can be cleaned."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..utils import (
    XcodeItem,
    XcodeItemType,
    XcodeScanResults,
    is_macos,
    parse_xcode_version,
)


class XcodeScanner:
    """
    Scans for Xcode-related data that can be cleaned up.

    Provides granular control over:
    - Device Support files (per iOS/watchOS/tvOS/visionOS version)
    - Derived Data (per project)
    - Archives (per archive with app version info)
    - Simulators (per device)
    - Documentation cache
    - Device logs

    Only runs on macOS.
    """

    # Xcode directories relative to home
    XCODE_PATHS = {
        "device_support": {
            "iOS": "Library/Developer/Xcode/iOS DeviceSupport",
            "watchOS": "Library/Developer/Xcode/watchOS DeviceSupport",
            "tvOS": "Library/Developer/Xcode/tvOS DeviceSupport",
            "visionOS": "Library/Developer/Xcode/visionOS DeviceSupport",
        },
        "derived_data": "Library/Developer/Xcode/DerivedData",
        "archives": "Library/Developer/Xcode/Archives",
        "simulators": "Library/Developer/CoreSimulator/Devices",
        "documentation": "Library/Developer/Xcode/DocumentationCache",
        "device_logs": "Library/Developer/Xcode/iOS Device Logs",
    }

    def __init__(self) -> None:
        """Initialize the Xcode scanner."""
        self.home = Path.home()

    def scan(
        self,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> XcodeScanResults:
        """
        Scan for Xcode-related items.

        Args:
            progress_callback: Optional callback(items_found, current_name)

        Returns:
            XcodeScanResults containing all found items
        """
        results = XcodeScanResults()

        # Only run on macOS
        if not is_macos():
            return results

        # Scan each category
        self._scan_device_support(results, progress_callback)
        self._scan_derived_data(results, progress_callback)
        self._scan_archives(results, progress_callback)
        self._scan_simulator_runtimes(results, progress_callback)
        self._scan_documentation(results, progress_callback)
        self._scan_device_logs(results, progress_callback)

        return results

    def _get_directory_size(self, path: Path) -> int:
        """Get total size of a directory."""
        total = 0
        try:
            for root, _, files in os.walk(path):
                for fname in files:
                    try:
                        fpath = Path(root) / fname
                        total += fpath.stat().st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total

    def _get_directory_mtime(self, path: Path) -> datetime:
        """Get most recent modification time in a directory."""
        try:
            latest = path.stat().st_mtime
            for root, _, files in os.walk(path):
                for fname in files:
                    try:
                        fpath = Path(root) / fname
                        mtime = fpath.stat().st_mtime
                        if mtime > latest:
                            latest = mtime
                    except (OSError, PermissionError):
                        continue
            return datetime.fromtimestamp(latest)
        except (OSError, PermissionError):
            return datetime.now()

    def _scan_device_support(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Device Support directories for each platform."""
        # Track latest version per platform for marking
        platform_versions: dict[str, list[tuple[tuple[int, ...], Path]]] = {}

        for platform_name, rel_path in self.XCODE_PATHS["device_support"].items():
            support_dir = self.home / rel_path

            if not support_dir.exists() or not support_dir.is_dir():
                continue

            platform_versions[platform_name] = []

            try:
                for entry in os.scandir(support_dir):
                    if not entry.is_dir():
                        continue

                    try:
                        version, build = parse_xcode_version(entry.name)
                        path = Path(entry.path)
                        size = self._get_directory_size(path)
                        mtime = self._get_directory_mtime(path)

                        # Track for latest detection
                        if version:
                            platform_versions[platform_name].append((version, path))

                        item = XcodeItem(
                            path=path,
                            name=entry.name,
                            item_type=XcodeItemType.DEVICE_SUPPORT,
                            size=size,
                            last_modified=mtime,
                            platform=platform_name,
                            version=version,
                            build=build,
                            is_latest=False,  # Will be set after scanning all
                        )
                        results.items.append(item)

                        if progress_callback:
                            progress_callback(
                                len(results.items), f"{platform_name} {entry.name}"
                            )

                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{entry.path}: {e}")

            except (OSError, PermissionError) as e:
                results.scan_errors.append(f"{support_dir}: {e}")

        # Mark latest versions per platform
        for platform_name, versions in platform_versions.items():
            if not versions:
                continue
            # Find the maximum version
            latest_version = max(versions, key=lambda x: x[0])[0]
            # Mark all items with this version as latest
            for item in results.items:
                if (
                    item.item_type == XcodeItemType.DEVICE_SUPPORT
                    and item.platform == platform_name
                    and item.version == latest_version
                ):
                    item.is_latest = True

    def _scan_derived_data(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Derived Data directory for build artifacts."""
        derived_data_dir = self.home / self.XCODE_PATHS["derived_data"]

        if not derived_data_dir.exists() or not derived_data_dir.is_dir():
            return

        try:
            for entry in os.scandir(derived_data_dir):
                if not entry.is_dir():
                    continue

                # Skip ModuleCache and other non-project dirs
                if entry.name in ("ModuleCache", "ModuleCache.noindex"):
                    continue

                try:
                    path = Path(entry.path)
                    size = self._get_directory_size(path)
                    mtime = self._get_directory_mtime(path)

                    # Extract project name from folder (format: ProjectName-hash)
                    parts = entry.name.rsplit("-", 1)
                    project_name = parts[0] if len(parts) > 1 else entry.name

                    item = XcodeItem(
                        path=path,
                        name=project_name,
                        item_type=XcodeItemType.DERIVED_DATA,
                        size=size,
                        last_modified=mtime,
                        platform=None,
                        version=None,
                        build=None,
                        is_latest=False,  # Derived data can always be deleted
                    )
                    results.items.append(item)

                    if progress_callback:
                        progress_callback(
                            len(results.items), f"Derived: {project_name}"
                        )

                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{entry.path}: {e}")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{derived_data_dir}: {e}")

    def _scan_archives(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Archives directory for app archives."""
        import plistlib

        archives_dir = self.home / self.XCODE_PATHS["archives"]

        if not archives_dir.exists() or not archives_dir.is_dir():
            return

        # Archives are organized by date: Archives/YYYY-MM-DD/*.xcarchive
        try:
            for date_entry in os.scandir(archives_dir):
                if not date_entry.is_dir():
                    continue

                for archive_entry in os.scandir(date_entry.path):
                    if not archive_entry.name.endswith(".xcarchive"):
                        continue

                    try:
                        path = Path(archive_entry.path)
                        size = self._get_directory_size(path)
                        mtime = self._get_directory_mtime(path)

                        # Try to parse Info.plist for app details
                        app_info = None
                        display_name = archive_entry.name.replace(".xcarchive", "")
                        info_plist = path / "Info.plist"

                        if info_plist.exists():
                            try:
                                with open(info_plist, "rb") as f:
                                    plist = plistlib.load(f)

                                app_props = plist.get("ApplicationProperties", {})
                                app_info = {
                                    "name": plist.get("Name", display_name),
                                    "bundle_id": app_props.get(
                                        "CFBundleIdentifier", "Unknown"
                                    ),
                                    "version": app_props.get(
                                        "CFBundleShortVersionString", "?"
                                    ),
                                    "build": app_props.get("CFBundleVersion", "?"),
                                }
                                # Create a nice display name
                                display_name = (
                                    f"{app_info['name']} {app_info['version']} "
                                    f"({app_info['build']})"
                                )
                            except Exception:
                                pass

                        item = XcodeItem(
                            path=path,
                            name=display_name,
                            item_type=XcodeItemType.ARCHIVE,
                            size=size,
                            last_modified=mtime,
                            platform=None,
                            version=None,
                            build=None,
                            is_latest=False,
                            app_info=app_info,
                        )
                        results.items.append(item)

                        if progress_callback:
                            progress_callback(
                                len(results.items), f"Archive: {display_name}"
                            )

                    except (OSError, PermissionError) as e:
                        results.scan_errors.append(f"{archive_entry.path}: {e}")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{archives_dir}: {e}")

    def _scan_simulator_runtimes(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan for simulator runtimes using xcrun simctl."""
        # Try to get runtime list from simctl
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "runtime", "list", "-v"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # simctl not available or failed
                results.scan_errors.append(
                    "Could not list simulator runtimes (xcrun simctl failed)"
                )
                return

            output = result.stdout
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            results.scan_errors.append(f"Could not run xcrun simctl: {e}")
            return

        # Parse the output to extract runtime info
        # Track versions per platform for marking latest
        platform_versions: dict[str, list[tuple[tuple[int, ...], int]]] = {}

        current_runtime: dict | None = None

        for line in output.split("\n"):
            line = line.strip()

            # Match runtime header: "iOS 26.2 (23C54) - UUID"
            runtime_match = re.match(
                r"^(\w+)\s+([\d.]+)\s+\(([^)]+)\)\s+-\s+([A-F0-9-]+)$", line
            )
            if runtime_match:
                # Save previous runtime if exists
                if current_runtime and current_runtime.get("deletable"):
                    self._add_runtime_item(
                        results, current_runtime, platform_versions, progress_callback
                    )

                platform = runtime_match.group(1)  # iOS, tvOS, watchOS
                version_str = runtime_match.group(2)  # 26.2
                build = runtime_match.group(3)  # 23C54
                uuid = runtime_match.group(4)

                # Parse version
                try:
                    version = tuple(int(v) for v in version_str.split("."))
                except ValueError:
                    version = None

                current_runtime = {
                    "platform": platform,
                    "version": version,
                    "version_str": version_str,
                    "build": build,
                    "uuid": uuid,
                    "size": 0,
                    "deletable": False,
                    "path": None,
                }
                continue

            if current_runtime:
                # Parse Size: 7.8G
                size_match = re.match(r"Size:\s+([\d.]+)([KMGT]?)B?", line)
                if size_match:
                    size_num = float(size_match.group(1))
                    size_unit = size_match.group(2)
                    multipliers = {
                        "": 1,
                        "K": 1024,
                        "M": 1024**2,
                        "G": 1024**3,
                        "T": 1024**4,
                    }
                    current_runtime["size"] = int(
                        size_num * multipliers.get(size_unit, 1)
                    )
                    continue

                # Parse Deletable: YES/NO
                if line.startswith("Deletable:"):
                    current_runtime["deletable"] = "YES" in line
                    continue

                # Parse Mount Path
                if line.startswith("Mount Path:"):
                    current_runtime["path"] = line.split(":", 1)[1].strip()
                    continue

        # Don't forget the last runtime
        if current_runtime and current_runtime.get("deletable"):
            self._add_runtime_item(
                results, current_runtime, platform_versions, progress_callback
            )

        # Mark latest versions per platform
        for platform_name, versions in platform_versions.items():
            if not versions:
                continue
            # Find the maximum version
            latest_version = max(versions, key=lambda x: x[0])[0]
            # Mark all items with this version as latest
            for item in results.items:
                if (
                    item.item_type == XcodeItemType.SIMULATOR_RUNTIME
                    and item.platform == platform_name
                    and item.version == latest_version
                ):
                    item.is_latest = True

    def _add_runtime_item(
        self,
        results: XcodeScanResults,
        runtime: dict,
        platform_versions: dict,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Add a simulator runtime item to results."""
        platform = runtime["platform"]
        version = runtime["version"]
        version_str = runtime["version_str"]
        build = runtime["build"]

        # Display name: "tvOS 16.0 (20J373)"
        display_name = f"{platform} {version_str} ({build})"

        # Track for latest detection
        if version:
            if platform not in platform_versions:
                platform_versions[platform] = []
            platform_versions[platform].append((version, len(results.items)))

        item = XcodeItem(
            path=Path(runtime.get("path") or f"/simctl:{runtime['uuid']}"),
            name=display_name,
            item_type=XcodeItemType.SIMULATOR_RUNTIME,
            size=runtime["size"],
            last_modified=datetime.now(),  # simctl doesn't give us this
            platform=platform,
            version=version,
            build=build,
            is_latest=False,
            app_info={"uuid": runtime["uuid"]},  # Store UUID for deletion
        )
        results.items.append(item)

        if progress_callback:
            progress_callback(len(results.items), f"Runtime: {display_name}")

    def _scan_documentation(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Documentation cache directory."""
        docs_dir = self.home / self.XCODE_PATHS["documentation"]

        if not docs_dir.exists() or not docs_dir.is_dir():
            return

        try:
            size = self._get_directory_size(docs_dir)
            mtime = self._get_directory_mtime(docs_dir)

            # Only add if there's actual content
            if size > 0:
                item = XcodeItem(
                    path=docs_dir,
                    name="Documentation Cache",
                    item_type=XcodeItemType.DOCUMENTATION,
                    size=size,
                    last_modified=mtime,
                    platform=None,
                    version=None,
                    build=None,
                    is_latest=False,
                )
                results.items.append(item)

                if progress_callback:
                    progress_callback(len(results.items), "Documentation Cache")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{docs_dir}: {e}")

    def _scan_device_logs(
        self,
        results: XcodeScanResults,
        progress_callback: Callable[[int, str], None] | None,
    ) -> None:
        """Scan Device Logs directory."""
        logs_dir = self.home / self.XCODE_PATHS["device_logs"]

        if not logs_dir.exists() or not logs_dir.is_dir():
            return

        try:
            # Scan per-device log folders
            for entry in os.scandir(logs_dir):
                if not entry.is_dir():
                    continue

                try:
                    path = Path(entry.path)
                    size = self._get_directory_size(path)
                    mtime = self._get_directory_mtime(path)

                    # Only add if there's actual content
                    if size > 0:
                        item = XcodeItem(
                            path=path,
                            name=f"Device Logs: {entry.name}",
                            item_type=XcodeItemType.DEVICE_LOGS,
                            size=size,
                            last_modified=mtime,
                            platform=None,
                            version=None,
                            build=None,
                            is_latest=False,
                        )
                        results.items.append(item)

                        if progress_callback:
                            progress_callback(len(results.items), f"Logs: {entry.name}")

                except (OSError, PermissionError) as e:
                    results.scan_errors.append(f"{entry.path}: {e}")

        except (OSError, PermissionError) as e:
            results.scan_errors.append(f"{logs_dir}: {e}")
