"""Read ReplayGain tags from local audio files.

ReplayGain gain values are stored differently per container:
  - Vorbis comments (FLAC/OGG): plain tags.get('replaygain_track_gain')
  - ID3 (MP3): a TXXX frame whose description is 'replaygain_track_gain'
  - MP4/M4A: a freeform atom '----:com.apple.iTunes:replaygain_track_gain'

All three represent the value as a string like "-3.20 dB".
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("radiomaster")

_GAIN_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _parse_db(value: str) -> float | None:
    match = _GAIN_RE.search(value)
    return float(match.group()) if match else None


def read_replaygain_db(file_path: str, mode: str) -> float:
    """Return the ReplayGain adjustment in dB for *file_path*, or 0.0 if
    unavailable/mode is "none". *mode* is "track" or "album"."""
    if mode not in ("track", "album"):
        return 0.0

    try:
        import mutagen
        audio = mutagen.File(file_path)
    except Exception as e:
        logger.debug(f"ReplayGain: could not open {file_path}: {e}")
        return 0.0
    if audio is None or audio.tags is None:
        return 0.0

    key = f"replaygain_{mode}_gain"
    other_key = f"replaygain_{'album' if mode == 'track' else 'track'}_gain"

    # Vorbis comments (FLAC, OGG): plain dict-like access, case-insensitive keys.
    try:
        for k in (key, key.upper(), other_key, other_key.upper()):
            if k in audio.tags:
                values = audio.tags[k]
                value = values[0] if isinstance(values, list) else values
                db = _parse_db(str(value))
                if db is not None:
                    return db
    except (TypeError, KeyError):
        pass

    # ID3 (MP3): TXXX frames carry a description + value. Prefer an exact
    # match on the requested mode; only fall back to the other mode's tag
    # if the requested one truly isn't present.
    try:
        found = {}
        for frame in audio.tags.getall("TXXX"):
            desc = (frame.desc or "").lower()
            if desc in (key, other_key) and frame.text:
                db = _parse_db(str(frame.text[0]))
                if db is not None:
                    found[desc] = db
        if key in found:
            return found[key]
        if other_key in found:
            return found[other_key]
    except AttributeError:
        pass

    # MP4/M4A: freeform atoms under the iTunes namespace.
    try:
        for tag_key in (f"----:com.apple.iTunes:{key}", f"----:com.apple.iTunes:{other_key}"):
            if tag_key in audio.tags:
                raw = audio.tags[tag_key][0]
                text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
                db = _parse_db(text)
                if db is not None:
                    return db
    except (AttributeError, KeyError):
        pass

    return 0.0
