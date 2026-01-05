"""Configuration module for managing user settings."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# tomllib is Python 3.11+, use tomli as fallback
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

# Global cached config
_cached_config: "Config | None" = None


@dataclass
class Config:
    """User configuration settings for yeet."""

    # Disk explorer settings
    start_path: str = "~"  # Starting directory for disk explorer
    min_size_mb: int = 5  # Minimum size to show in explorer
    show_hidden: bool = True  # Show hidden files/dirs

    # Deletion settings
    use_trash: bool = True  # Move to trash instead of permanent delete
    confirm_delete: bool = True  # Ask for confirmation before delete

    # Display settings
    color_enabled: bool = True  # Use colors in output

    # Scanner settings
    days_threshold: int = 90  # Days to consider project stale
    large_file_mb: int = 25  # Minimum size for large files
    cache_size_mb: int = 1  # Minimum cache size to show

    # Cache settings
    cache_enabled: bool = True  # Persist size cache to disk
    cache_max_age_hours: int = 24  # Max age of cached sizes

    @staticmethod
    def get_default_path() -> Path:
        """Return default config path."""
        return Path.home() / ".config" / "yeet" / "config.toml"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load config from TOML file.

        Args:
            path: Path to config file. Defaults to ~/.config/yeet/config.toml

        Returns:
            Config instance with loaded or default values.
        """
        config_path = path or cls.get_default_path()

        if not config_path.exists():
            return cls()

        try:
            if tomllib is None:
                # No TOML parser available, use defaults
                return cls()
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, Exception):
            # Catch all exceptions including TOMLDecodeError
            return cls()

        # Map TOML sections to flat dataclass fields
        kwargs = {}

        # Explorer section
        if "explorer" in data:
            explorer = data["explorer"]
            if "start_path" in explorer:
                kwargs["start_path"] = explorer["start_path"]
            if "min_size_mb" in explorer:
                kwargs["min_size_mb"] = explorer["min_size_mb"]
            if "show_hidden" in explorer:
                kwargs["show_hidden"] = explorer["show_hidden"]

        # Deletion section
        if "deletion" in data:
            deletion = data["deletion"]
            if "use_trash" in deletion:
                kwargs["use_trash"] = deletion["use_trash"]
            if "confirm_delete" in deletion:
                kwargs["confirm_delete"] = deletion["confirm_delete"]

        # Display section
        if "display" in data:
            display = data["display"]
            if "color_enabled" in display:
                kwargs["color_enabled"] = display["color_enabled"]

        # Scanner section
        if "scanner" in data:
            scanner = data["scanner"]
            if "days_threshold" in scanner:
                kwargs["days_threshold"] = scanner["days_threshold"]
            if "large_file_mb" in scanner:
                kwargs["large_file_mb"] = scanner["large_file_mb"]
            if "cache_size_mb" in scanner:
                kwargs["cache_size_mb"] = scanner["cache_size_mb"]

        # Cache section
        if "cache" in data:
            cache = data["cache"]
            if "enabled" in cache:
                kwargs["cache_enabled"] = cache["enabled"]
            if "max_age_hours" in cache:
                kwargs["cache_max_age_hours"] = cache["max_age_hours"]

        return cls(**kwargs)

    def save(self, path: Path | None = None) -> bool:
        """Save config to TOML file.

        Args:
            path: Path to config file. Defaults to ~/.config/yeet/config.toml

        Returns:
            True if save succeeded, False otherwise.
        """
        config_path = path or self.get_default_path()

        # Build TOML content manually
        lines = ["# Yeet Configuration", ""]

        # Explorer section
        lines.append("[explorer]")
        lines.append(f'start_path = "{self.start_path}"')
        lines.append(f"min_size_mb = {self.min_size_mb}")
        lines.append(f"show_hidden = {str(self.show_hidden).lower()}")
        lines.append("")

        # Deletion section
        lines.append("[deletion]")
        lines.append(f"use_trash = {str(self.use_trash).lower()}")
        lines.append(f"confirm_delete = {str(self.confirm_delete).lower()}")
        lines.append("")

        # Display section
        lines.append("[display]")
        lines.append(f"color_enabled = {str(self.color_enabled).lower()}")
        lines.append("")

        # Scanner section
        lines.append("[scanner]")
        lines.append(f"days_threshold = {self.days_threshold}")
        lines.append(f"large_file_mb = {self.large_file_mb}")
        lines.append(f"cache_size_mb = {self.cache_size_mb}")
        lines.append("")

        # Cache section
        lines.append("[cache]")
        lines.append(f"enabled = {str(self.cache_enabled).lower()}")
        lines.append(f"max_age_hours = {self.cache_max_age_hours}")
        lines.append("")

        content = "\n".join(lines)

        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(content)
            return True
        except OSError:
            return False


def get_config() -> Config:
    """Get cached global config instance.

    Returns:
        Config instance (loaded once and cached).
    """
    global _cached_config
    if _cached_config is None:
        _cached_config = Config.load()
    return _cached_config
