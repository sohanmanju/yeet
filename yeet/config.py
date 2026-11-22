"""Configuration module for managing user settings."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models import DAYS_SINCE_ACCESS, DEFAULT_LARGE_FILE_MB

# tomllib is Python 3.11+, use tomli as fallback
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


_cached_config: "Config | None" = None


CONFIG_SECTIONS = {
    "explorer": {
        "start_path": "start_path",
        "min_size_mb": "min_size_mb",
        "show_hidden": "show_hidden",
    },
    "deletion": {"use_trash": "use_trash", "confirm_delete": "confirm_delete"},
    "display": {"color_enabled": "color_enabled"},
    "scanner": {
        "days_threshold": "days_threshold",
        "large_file_mb": "large_file_mb",
        "cache_size_mb": "cache_size_mb",
    },
    "cache": {"enabled": "cache_enabled", "max_age_hours": "cache_max_age_hours"},
    "paths": {
        "protected_paths": "protected_paths",
        "ignored_paths": "ignored_paths",
        "bookmarks": "bookmarks",
    },
}
PATH_LISTS = frozenset(CONFIG_SECTIONS["paths"].values())


@dataclass
class Config:
    """User configuration settings for yeet."""

    start_path: str = "~"
    min_size_mb: int = 5
    show_hidden: bool = True

    use_trash: bool = True
    confirm_delete: bool = True

    color_enabled: bool = True

    days_threshold: int = DAYS_SINCE_ACCESS
    large_file_mb: int = DEFAULT_LARGE_FILE_MB
    cache_size_mb: int = 1

    cache_enabled: bool = True
    cache_max_age_hours: int = 24

    protected_paths: list[str] = field(default_factory=list)
    ignored_paths: list[str] = field(default_factory=list)
    bookmarks: list[str] = field(default_factory=list)

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
                return cls()
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, ValueError):
            return cls()

        kwargs = {}
        for section, settings in CONFIG_SECTIONS.items():
            values = data.get(section, {})
            for key, attribute in settings.items():
                if key in values:
                    value = values[key]
                    kwargs[attribute] = (
                        list(value) if attribute in PATH_LISTS else value
                    )

        return cls(**kwargs)

    def save(self, path: Path | None = None) -> bool:
        """Save config to TOML file.

        Args:
            path: Path to config file. Defaults to ~/.config/yeet/config.toml

        Returns:
            True if save succeeded, False otherwise.
        """
        config_path = path or self.get_default_path()

        lines = ["# Yeet Configuration", ""]
        for section, settings in CONFIG_SECTIONS.items():
            lines.append(f"[{section}]")
            for key, attribute in settings.items():
                lines.append(
                    f"{key} = {json.dumps(getattr(self, attribute), ensure_ascii=False)}"
                )
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
