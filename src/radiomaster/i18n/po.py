"""Minimal .po reader, so translations need no compile step."""

from __future__ import annotations

import ast
import os


def _unquote(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return ""
    return value if isinstance(value, str) else ""


def parse_po(path: str) -> dict[str, str]:
    """Return {msgid: msgstr}; entries with an empty msgstr are left out."""
    entries: dict[str, str] = {}
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    target: list[str] | None = None

    def flush() -> None:
        if msgid is not None and msgstr is not None:
            key, value = "".join(msgid), "".join(msgstr)
            if key and value:
                entries[key] = value

    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return {}
    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid, msgstr = [_unquote(line[6:])], None
            target = msgid
        elif line.startswith("msgstr "):
            msgstr = [_unquote(line[7:])]
            target = msgstr
        elif line.startswith('"') and target is not None:
            target.append(_unquote(line))
        elif not line:
            flush()
            msgid = msgstr = target = None
    flush()
    return entries


def catalogue_path(locale_dir: str, lang: str) -> str:
    return os.path.join(locale_dir, lang, "LC_MESSAGES", "radiomaster.po")
