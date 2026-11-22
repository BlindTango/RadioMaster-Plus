"""Tell a station that is blocked in the listener's region from one that is down.

BASS reports both as the same "could not be opened" error. Many stations are
licensed only for listeners in their own country and refuse everyone else with
HTTP 403 or 451, so after a failed open the address is asked once more with a
plain request to find out which it was.

HLS streams hide the block one level down: the top playlist is open to
everyone, but the playlist or audio it points to refuses listeners abroad. Those
are followed a few steps to find the refusal.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import requests

BLOCK_STATUSES = (403, 451)
_HLS_TYPES = ("mpegurl", "x-mpegurl")
_MAX_HLS_REQUESTS = 4


def is_hls(url: str, content_type: str = "") -> bool:
    return (any(kind in (content_type or "").lower() for kind in _HLS_TYPES)
            or urlsplit(url).path.lower().endswith(".m3u8"))


def _first_uri(playlist: str, base: str) -> str | None:
    """The first playlist or segment address in an HLS playlist."""
    for line in playlist.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return urljoin(base, line)
    match = re.search(r'URI="([^"]+)"', playlist)
    return urljoin(base, match.group(1)) if match else None


def region_block_status(url: str, timeout: float = 6.0) -> int | None:
    """The HTTP status (403 or 451) if the station refuses this connection,
    otherwise None. Follows HLS playlists to the audio. Never raises."""
    if not url.startswith(("http://", "https://")):
        return None
    from radiomaster.utils.network import get_proxies, get_user_agent
    headers = {"Icy-MetaData": "1", "User-Agent": get_user_agent("RadioMaster+/1.0")}
    proxies = get_proxies()
    current = url
    try:
        for _ in range(_MAX_HLS_REQUESTS):
            response = requests.get(current, headers=headers, proxies=proxies, stream=True,
                                    timeout=timeout, allow_redirects=True)
            try:
                if response.status_code in BLOCK_STATUSES:
                    return response.status_code
                if response.status_code != 200 or not is_hls(
                        response.url, response.headers.get("Content-Type", "")):
                    return None
                text = response.raw.read(65536, decode_content=True).decode("utf-8", "replace")
                nxt = _first_uri(text, response.url)
            finally:
                response.close()
            if not nxt:
                return None
            current = nxt
    except Exception:
        return None
    return None


def region_block_message(status: int) -> str:
    return (
        f"This station refused the connection (HTTP {status}). Many stations are licensed "
        "only for listeners in their own country, so it may play through a VPN in that "
        "country. Settings > Network > Regional routing can switch your VPN to the "
        "station's country automatically. Otherwise, choose a similar station, or look "
        "for the broadcaster's international stream or podcasts, which often play anywhere."
    )
