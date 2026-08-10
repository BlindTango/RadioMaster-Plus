"""Probes a live stream URL for its actual broadcast audio format.

The Radio-Browser station database's codec/bitrate fields are
self-reported by whoever submitted the station and are frequently
missing, stale, or simply wrong (a station can claim "MP3" while
actually serving AAC, or list no bitrate at all). ffprobe asks the
stream itself instead of trusting the index.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Optional, TypedDict

from radiomaster.utils.tools import get_ffprobe

logger = logging.getLogger("radiomaster")


class StreamFormat(TypedDict):
    codec: str  # ffprobe's codec_name, e.g. "mp3", "aac", "flac", "vorbis", "opus"
    sample_rate: int  # Hz, 0 if ffprobe couldn't determine it
    channels: int  # 0 if unknown
    bit_rate: int  # bits/sec, 0 if unknown or genuinely variable


def probe_stream_format(url: str, timeout: float = 8.0) -> Optional[StreamFormat]:
    """Runs ffprobe against *url* and returns the first audio stream's
    real codec/sample-rate/channels/bitrate, or None if probing failed
    (station unreachable, ffprobe timed out, or no audio stream found).
    Bounded analyzeduration/probesize keep this from hanging on a slow
    or silent stream -- worst case it just gives up within *timeout*."""
    cmd = [
        get_ffprobe(), "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", "-select_streams", "a:0",
        "-analyzeduration", "3000000", "-probesize", "500000",
        url,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        # Probing is always best-effort (falls back to the configured
        # recording format/quality) -- must never raise into the caller,
        # whatever the failure mode (unreachable station, ffprobe
        # missing, malformed output, anything else).
        logger.debug(f"Stream format probe failed for {url}: {e}")
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    streams = data.get("streams") or []
    if not streams:
        return None
    stream = streams[0]
    codec = stream.get("codec_name", "") or ""

    def _int(value: object) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    sample_rate = _int(stream.get("sample_rate"))
    channels = _int(stream.get("channels"))
    # A live stream's per-stream bit_rate is often absent (VBR/unknown
    # container-level framing) even though the overall format-level one
    # ffprobe also reports usually isn't -- fall back to that.
    bit_rate = _int(stream.get("bit_rate")) or _int((data.get("format") or {}).get("bit_rate"))
    return {"codec": codec, "sample_rate": sample_rate, "channels": channels, "bit_rate": bit_rate}


def format_stream_format(fmt: Optional[StreamFormat]) -> str:
    """Human-readable summary for the status bar / station details, e.g.
    "FLAC, 44.1 kHz, Stereo, 855 kbps" -- omits any field ffprobe
    couldn't determine rather than showing a misleading 0."""
    if not fmt:
        return ""
    parts: list[str] = []
    if fmt["codec"]:
        parts.append(fmt["codec"].upper())
    if fmt["sample_rate"]:
        parts.append(f"{fmt['sample_rate'] / 1000:.1f} kHz")
    if fmt["channels"]:
        parts.append({1: "Mono", 2: "Stereo"}.get(fmt["channels"], f"{fmt['channels']}ch"))
    if fmt["bit_rate"]:
        parts.append(f"{fmt['bit_rate'] // 1000} kbps")
    return ", ".join(parts)
