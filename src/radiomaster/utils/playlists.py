"""Reading M3U/M3U8 and PLS playlist files."""

from __future__ import annotations

import configparser
import os

PLAYLIST_EXTENSIONS = (".m3u", ".m3u8", ".pls")


def is_playlist(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in PLAYLIST_EXTENSIONS


def _resolve(entry: str, base_dir: str) -> str:
    entry = entry.strip().strip('"')
    if "://" in entry:
        return entry
    if entry.lower().startswith("file:///"):
        entry = entry[8:]
    entry = entry.replace("/", os.sep)
    return entry if os.path.isabs(entry) else os.path.normpath(os.path.join(base_dir, entry))


def _read_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_playlist(path: str) -> list[str]:
    """Return the playable locations in a playlist, relative paths resolved
    against the playlist's folder. Unreadable files give an empty list."""
    base = os.path.dirname(os.path.abspath(path))
    try:
        text = _read_text(path)
    except OSError:
        return []
    entries: list[str] = []
    if path.lower().endswith(".pls"):
        parser = configparser.RawConfigParser(strict=False)
        try:
            parser.read_string(text)
        except configparser.Error:
            return []
        section = next((s for s in parser.sections() if s.lower() == "playlist"), None)
        if section is None:
            return []
        items = [(k, v) for k, v in parser.items(section) if k.lower().startswith("file")]
        items.sort(key=lambda kv: int("".join(c for c in kv[0] if c.isdigit()) or 0))
        entries = [v for _k, v in items]
    else:
        entries = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return [_resolve(e, base) for e in entries if e.strip()]


def write_m3u(path: str, locations: list[str], titles: list[str] | None = None) -> None:
    """Write an extended M3U8 (UTF-8). Files in the playlist's own folder tree
    are stored relative so the playlist survives being moved with its media."""
    base = os.path.dirname(os.path.abspath(path))
    lines = ["#EXTM3U"]
    for i, loc in enumerate(locations):
        if titles and i < len(titles) and titles[i]:
            lines.append(f"#EXTINF:-1,{titles[i]}")
        if "://" not in loc:
            try:
                rel = os.path.relpath(loc, base)
                if not rel.startswith(".."):
                    loc = rel
            except ValueError:  # different drive
                pass
        lines.append(loc)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
