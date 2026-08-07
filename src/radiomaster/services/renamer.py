"""Track renaming service.

Provides a tiny template engine that substitutes placeholders in a user‑defined
string with values from a track dictionary.  Placeholders follow the standard
Python ``str.format`` syntax, e.g. ``"{artist} - {title}"``.

The service is deliberately lightweight – it does not attempt to parse complex
expressions or handle missing keys; instead it falls back to an empty string
for any unknown placeholder.
"""

from __future__ import annotations

from typing import Mapping


class Renamer:
    """Utility class for rendering track‑renaming templates.

    Example
    -------
    >>> r = Renamer()
    >>> tmpl = "{artist} - {title}"
    >>> r.render(tmpl, {"artist": "Foo", "title": "Bar"})
    'Foo - Bar'
    """

    @staticmethod
    def render(template: str, data: Mapping[str, str]) -> str:
        """Render *template* using *data*.

        Missing keys are replaced with an empty string to avoid ``KeyError``.
        """
        class SafeDict(dict):
            def __missing__(self, key: str) -> str:  # type: ignore[override]
                return ""

        safe_data = SafeDict(data)
        try:
            return template.format_map(safe_data)
        except Exception:
            # In case of malformed format strings, return the original template.
            return template
