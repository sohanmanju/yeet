"""Filesystem operations and platform integration."""

from __future__ import annotations
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def delete_file(path: Path) -> tuple[bool, str]:
    """Delete a file and return success status with message."""
    try:
        if path.is_file():
            path.unlink()
            return True, f"Deleted: {path}"
        return False, f"Not a file: {path}"
    except PermissionError:
        return False, f"Permission denied: {path}"
    except OSError as e:
        return False, f"Error deleting {path}: {e}"


def delete_directory(path: Path) -> tuple[bool, str]:
    """Delete a directory and all its contents."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
            return True, f"Deleted directory: {path}"
        return False, f"Not a directory: {path}"
    except PermissionError:
        return False, f"Permission denied: {path}"
    except OSError as e:
        return False, f"Error deleting {path}: {e}"


def trash_available() -> bool:
    """
    Check if system trash is supported on the current platform.

    Returns:
        True if trash functionality is available, False otherwise.
    """
    system = platform.system().lower()

    if system == "darwin":
        # macOS always has Trash via osascript
        return True
    elif system == "linux":
        # Linux uses freedesktop.org trash spec

        return True
    elif system == "windows":
        # Windows requires send2trash library
        try:
            import send2trash  # noqa: F401

            return True
        except ImportError:
            return False
    else:
        return False


def move_to_trash(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to the system trash instead of permanent deletion.

    This function provides cross-platform trash support:
    - macOS: Uses osascript to move to Trash (most reliable method)
    - Linux: Moves to ~/.local/share/Trash/ following freedesktop.org spec
    - Windows: Uses send2trash library if available, otherwise returns an error

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message) where success is True if the item
        was moved to trash successfully.
    """
    try:
        path = path.resolve()

        if not path.exists():
            return False, f"Path does not exist: {path}"

        system = platform.system().lower()

        if system == "darwin":
            return _trash_macos(path)
        elif system == "linux":
            return _trash_linux(path)
        elif system == "windows":
            return _trash_windows(path)
        else:
            return False, f"Unsupported platform for trash: {system}"

    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        return False, f"Error moving to trash: {e}"


def _trash_macos(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to Trash on macOS using osascript.

    This is the most reliable method as it properly handles:
    - Trash metadata (.DS_Store, etc.)
    - "Put Back" functionality
    - Name conflicts (automatically appends numbers)

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message)
    """
    try:
        # This is more reliable than moving to ~/.Trash directly
        # as it handles all the metadata and "Put Back" functionality
        script = f'''
            tell application "Finder"
                delete POSIX file "{path}"
            end tell
        '''
        # Use a longer timeout (120s) for large directories
        # Finder can be slow when trashing many files
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return True, f"Moved to Trash: {path}"
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"

            if (
                "permission" in error_msg.lower()
                or "not have permission" in error_msg.lower()
            ):
                return False, f"Permission denied (some items may be protected): {path}"
            return False, f"Failed to move to Trash: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, f"Timeout moving to Trash (directory may be too large): {path}"
    except FileNotFoundError:
        return False, "osascript command not found"
    except Exception as e:
        return False, f"Error moving to Trash: {e}"


def _trash_linux(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to Trash on Linux.

    Follows the freedesktop.org Trash specification:
    - Files go to ~/.local/share/Trash/files/
    - Info files go to ~/.local/share/Trash/info/

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message)
    """
    try:
        trash_base = Path.home() / ".local" / "share" / "Trash"
        trash_files = trash_base / "files"
        trash_info = trash_base / "info"

        trash_files.mkdir(parents=True, exist_ok=True)
        trash_info.mkdir(parents=True, exist_ok=True)

        trash_name = path.name
        trash_path = trash_files / trash_name
        info_path = trash_info / f"{trash_name}.trashinfo"

        if trash_path.exists() or info_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            base_name = path.stem if path.is_file() else path.name
            suffix = path.suffix if path.is_file() else ""
            trash_name = f"{base_name}_{timestamp}{suffix}"
            trash_path = trash_files / trash_name
            info_path = trash_info / f"{trash_name}.trashinfo"

        # Create the .trashinfo file (freedesktop.org spec)
        deletion_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        from urllib.parse import quote

        encoded_path = quote(str(path), safe="/")
        info_content = f"""[Trash Info]
Path={encoded_path}
DeletionDate={deletion_date}
"""

        info_path.write_text(info_content)

        try:
            shutil.move(str(path), str(trash_path))
        except Exception as e:
            info_path.unlink(missing_ok=True)
            raise e

        return True, f"Moved to Trash: {path}"

    except PermissionError:
        return False, f"Permission denied: {path}"
    except Exception as e:
        return False, f"Error moving to Trash: {e}"


def _trash_windows(path: Path) -> tuple[bool, str]:
    """
    Move a file or directory to Recycle Bin on Windows.

    Uses the send2trash library if available, otherwise returns an error.

    Args:
        path: Path to the file or directory to trash

    Returns:
        Tuple of (success, message)
    """
    try:
        import send2trash

        send2trash.send2trash(str(path))
        return True, f"Moved to Recycle Bin: {path}"
    except ImportError:
        return (
            False,
            "Trash unavailable: install send2trash or explicitly confirm permanent deletion.",
        )
    except Exception as e:
        return False, f"Error moving to Recycle Bin: {e}"


def validate_directory(path_str: str) -> tuple[bool, Path | str]:
    """Validate that a path is a valid, accessible directory."""
    try:
        path = Path(path_str).expanduser().resolve()

        if not path.exists():
            return False, f"Path does not exist: {path}"

        if not path.is_dir():
            return False, f"Path is not a directory: {path}"

        try:
            next(os.scandir(path), None)
        except PermissionError:
            return False, f"Permission denied: {path}"

        return True, path

    except Exception as e:
        return False, f"Invalid path: {e}"


def is_macos() -> bool:
    """Check if running on macOS."""
    return platform.system().lower() == "darwin"


def open_path(path: Path) -> tuple[bool, str]:
    """
    Open a path in the system file manager.

    - macOS: Opens in Finder
    - Linux: Opens with xdg-open
    - Windows: Opens in Explorer

    Args:
        path: Path to open (file or directory)

    Returns:
        Tuple of (success, message)
    """
    try:
        if not path.exists():
            return False, f"Path does not exist: {path}"

        system = platform.system().lower()

        if system == "darwin":
            # -R reveals the file in Finder (selects it)
            if path.is_file():
                subprocess.run(["open", "-R", str(path)], check=True)
            else:
                subprocess.run(["open", str(path)], check=True)

        elif system == "linux":
            subprocess.run(["xdg-open", str(path)], check=True)

        elif system == "windows":
            if path.is_file():
                # /select highlights the file in Explorer
                subprocess.run(["explorer", "/select,", str(path)], check=True)
            else:
                subprocess.run(["explorer", str(path)], check=True)

        else:
            return False, f"Unsupported platform: {system}"

        return True, f"Opened: {path}"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to open: {e}"
    except FileNotFoundError:
        return False, "File manager command not found"
    except Exception as e:
        return False, f"Error opening path: {e}"


@dataclass(frozen=True)
class DirectoryStats:
    size: int
    file_count: int
    last_modified: datetime


def directory_stats(path: Path) -> DirectoryStats:
    """Measure apparent bytes, tolerating entries that disappear or deny access.

    Root metadata errors propagate so each scan can report or recover from them.
    Symlinked directories are not traversed; file stat follows links, matching
    the scanners' existing apparent-size policy.
    """
    latest = path.stat().st_mtime
    total = count = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                stat = (Path(root) / name).stat()
            except OSError:
                continue
            total += stat.st_size
            count += 1
            latest = max(latest, stat.st_mtime)
    return DirectoryStats(total, count, datetime.fromtimestamp(latest))
