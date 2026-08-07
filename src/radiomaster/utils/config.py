"""Configuration management for RadioMaster+."""

import json
import os
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "language": "en",
        "theme": "default",
        "startup_behavior": "normal",
        "minimize_to_tray": False,
    },
    "playback": {
        "default_volume": 0.8,
        "crossfade_duration": 3,
        "fade_in_duration": 0,
        "fade_out_duration": 0,
        "buffer_size": 4096,
        "default_rate": 1.0,
        # Last-used values, restored on next launch -- distinct from
        # default_volume/default_rate above, which are Settings-dialog
        # starting points, not "what was playing when you last closed
        # the app".
        "volume": 0.8,
        "rate": 1.0,
        "pan": 0.0,
    },
    "radio": {
        "auto_sync_on_startup": True,
        "sync_interval_hours": 24,
        "connection_timeout": 10,
        "retry_count": 3,
    },
    "downloads": {
        "download_folder": "",
        "max_concurrent": 3,
        "default_format": "auto",
        "auto_download_podcasts": False,
    },
    "recordings": {
        "output_folder": "",
        "default_format": "auto",
        "pre_buffer_seconds": 5,
    },
    "network": {
        "proxy": "",
        "timeout": 10,
        "retry_attempts": 3,
        "user_agent": "RadioMaster+/1.0",
    },
    "audio": {
        "device": "default",
        "sample_rate": 44100,
        "buffer_size": 4096,
    },
    "accessibility": {
        "highlight_color": "#FFFF00",
        "font_size": 12,
        "font_family": "",
        "dyslexia_font": False,
        "sapi_screen_reader_mode": "coexist",
    },
    "updates": {
        "check_frequency_days": 7,
        "channel": "stable",
    },
    "logging": {
        "level": "info",
    },
}


class ConfigManager:
    """Manages application configuration stored as JSON."""

    def __init__(self, config_dir: str) -> None:
        self._config_dir = config_dir
        self._config_file = os.path.join(config_dir, "settings.json")
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load configuration from disk, merging with defaults."""
        self._data = dict(DEFAULT_CONFIG)
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._deep_merge(self._data, saved)
            except (json.JSONDecodeError, OSError):
                pass

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Recursively merge override dict into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self) -> None:
        """Save configuration to disk."""
        os.makedirs(self._config_dir, exist_ok=True)
        with open(self._config_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, *keys: str, default: Any = None) -> Any:
        """Get a config value by nested keys.

        Supports both dotted notation (``'general.language'``) and variadic
        keys (``'general', 'language'``).  The first form is used by the
        settings dialog; the second is the canonical internal API.
        """
        value: Any = self._data
        # Flatten dotted keys into a single list
        flat_keys: list[str] = []
        for k in keys:
            flat_keys.extend(k.split("."))
        for key in flat_keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, *keys: str, value: Any) -> None:
        """Set a config value by nested keys.

        Supports both dotted notation (``'general.language'``) and variadic
        keys (``'general', 'language'``).
        """
        target = self._data
        flat_keys: list[str] = []
        for k in keys:
            flat_keys.extend(k.split("."))
        for key in flat_keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[flat_keys[-1]] = value

    @property
    def all(self) -> dict[str, Any]:
        """Return the full configuration dict."""
        return self._data

    # ------------------------------------------------------------------
    # Singleton accessor (used by services that don't hold a reference)
    # ------------------------------------------------------------------
    _instance: "ConfigManager | None" = None

    @staticmethod
    def get_instance() -> "ConfigManager":
        """Get or create the global ConfigManager singleton.

        This is used by services (e.g. :class:`LyricsService`) that need
        to read configuration but are not passed a ``ConfigManager``
        reference during construction.
        """
        if ConfigManager._instance is None:
            import os
            from platformdirs import user_config_dir
            from radiomaster import __app_name__
            app_name = __app_name__.replace("+", "Plus")
            config_dir = user_config_dir(app_name, app_name)
            ConfigManager._instance = ConfigManager(config_dir)
        return ConfigManager._instance

    def load(self) -> None:
        """Reload configuration from disk, discarding in-memory changes."""
        self._load()
