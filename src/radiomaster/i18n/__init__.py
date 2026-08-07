"""Internationalization setup for RadioMaster+."""

import gettext
import os
import locale
import logging
from typing import Any

from radiomaster import __app_name__

logger = logging.getLogger("radiomaster")

# Available languages with their display names
LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
}


class I18nManager:
    """Manages translations and localization."""

    _instance: "I18nManager | None" = None
    _current_language: str = "en"
    _translations: dict[str, Any] = {}

    def __new__(cls) -> "I18nManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._setup()

    def _setup(self) -> None:
        """Set up gettext translations for all available languages."""
        locale_dir = os.path.dirname(__file__)
        for lang in LANGUAGES:
            try:
                trans = gettext.translation(
                    "radiomaster", locale_dir, languages=[lang],
                    fallback=True,
                )
                self._translations[lang] = trans
            except FileNotFoundError:
                self._translations[lang] = gettext.NullTranslations()
                logger.debug(f"No translation file for {lang}")
            except Exception as e:
                self._translations[lang] = gettext.NullTranslations()
                logger.debug(f"Error loading {lang}: {e}")

    def set_language(self, lang: str) -> None:
        """Switch the active language."""
        if lang in self._translations:
            self._current_language = lang
            self._translations[lang].install()
            logger.info(f"Language set to {lang}")

    def gettext(self, message: str) -> str:
        """Translate a message."""
        trans = self._translations.get(self._current_language)
        if trans:
            return trans.gettext(message)
        return message

    @property
    def language(self) -> str:
        return self._current_language

    @property
    def available_languages(self) -> list[str]:
        return list(self._translations.keys())


# Convenience function
_ = I18nManager().gettext
