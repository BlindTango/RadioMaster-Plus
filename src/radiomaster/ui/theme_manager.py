"""Theme management for RadioMaster+."""

import json
import os
from typing import Any

from radiomaster.utils.config import ConfigManager


DEFAULT_THEMES: dict[str, dict[str, str]] = {
    "default": {
        "name": "Default Light",
        "bg_primary": "#FFFFFF",
        "bg_secondary": "#F0F0F0",
        "bg_tertiary": "#E0E0E0",
        "text_primary": "#000000",
        "text_secondary": "#333333",
        "accent": "#0078D4",
        "accent_hover": "#106EBE",
        "highlight": "#FFFF00",
        "highlight_text": "#000000",
        "success": "#107C10",
        "warning": "#FF8C00",
        "error": "#E81123",
        "border": "#CCCCCC",
        "control_face": "#E0E0E0",
        "control_text": "#000000",
    },
    "dark": {
        "name": "Default Dark",
        "bg_primary": "#1E1E1E",
        "bg_secondary": "#252526",
        "bg_tertiary": "#2D2D2D",
        "text_primary": "#D4D4D4",
        "text_secondary": "#AAAAAA",
        "accent": "#0078D4",
        "accent_hover": "#1A8AD4",
        "highlight": "#FFFF00",
        "highlight_text": "#000000",
        "success": "#4EC94E",
        "warning": "#FF8C00",
        "error": "#F14C4C",
        "border": "#3C3C3C",
        "control_face": "#333333",
        "control_text": "#D4D4D4",
    },
}


class ThemeManager:
    """Manages application themes and color schemes."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._themes: dict[str, dict[str, str]] = {}
        self._current_theme: str = "default"
        self._on_theme_changed: Any = None
        self._load_themes()

    def _custom_themes_path(self) -> str:
        from radiomaster.utils.paths import get_paths
        return os.path.join(get_paths()["config"], "custom_themes.json")

    def _load_themes(self) -> None:
        """Load built-in themes plus any saved custom themes."""
        self._themes = dict(DEFAULT_THEMES)
        try:
            path = self._custom_themes_path()
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._themes.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
        self._current_theme = self._config.get("general", "theme", default="default")

    def on_theme_changed(self, callback: Any) -> None:
        """Register a callback(theme_key) invoked whenever the active theme changes."""
        self._on_theme_changed = callback

    def get_color(self, key: str) -> str:
        """Get a color value from the current theme."""
        theme = self._themes.get(self._current_theme, self._themes["default"])
        return theme.get(key, "#000000")

    def get_theme_names(self) -> list[str]:
        """Get list of available theme names."""
        return [t["name"] for t in self._themes.values()]

    def get_theme_keys(self) -> list[str]:
        """Get list of available theme keys."""
        return list(self._themes.keys())

    def apply_theme(self, theme_key: str) -> None:
        """Switch to a different theme."""
        if theme_key in self._themes:
            self._current_theme = theme_key
            self._config.set("general", "theme", value=theme_key)
            self._config.save()
            if self._on_theme_changed:
                self._on_theme_changed(theme_key)

    def save_custom_theme(self, theme_key: str, colors: dict[str, str]) -> None:
        """Save a custom theme, persisted to disk so it survives a restart."""
        self._themes[theme_key] = colors
        try:
            custom = {k: v for k, v in self._themes.items() if k not in DEFAULT_THEMES}
            path = self._custom_themes_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(custom, f, indent=2)
        except OSError:
            pass
