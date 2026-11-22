"""Find HTTP audio streams behind public listen links without running scripts."""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from radiomaster.engine.bass_host import _iono_playlist_url
from radiomaster.utils.network import get_proxies, get_timeout, get_user_agent

_MEDIA_EXTENSION = re.compile(r"\.(?:mp3|aac|ogg|opus|m3u8?|pls|asx|flac|wav)(?:$|[?#])", re.I)
_LISTEN = re.compile(r"\b(?:listen|player?|live|stream|tune[ -]?in)\b", re.I)
_PLAYLIST_TYPES = {
    "audio/x-mpegurl",
    "audio/mpegurl",
    "application/x-mpegurl",
    "application/vnd.apple.mpegurl",
    "audio/x-scpls",
    "video/x-ms-asf",
}
_URL_LITERAL = re.compile(r"""["']((?:https?:)?//[^\s"'<>]+|/[^\s"'<>]+)["']""")
_STREAM_KEY = re.compile(
    r"""(?:file|src|stream(?:Url|_url)?|audio(?:Url|_url)?)['"]?\s*[:=]\s*$""", re.I
)


@dataclass(frozen=True)
class DiscoveredStream:
    url: str
    format: str
    source: str


@dataclass(frozen=True)
class DiscoveryResult:
    streams: tuple[DiscoveredStream, ...]
    pages_checked: int
    limited: bool = False
    cancelled: bool = False
    error: str = ""


_RADIO_GARDEN = re.compile(r"^/listen/[^/]+/([A-Za-z0-9_-]{6,})/?$")


def _radio_garden_url(url: str) -> str | None:
    """A public Radio Garden station page (radio.garden/listen/<name>/<id>) plays
    through a fixed address that redirects to the station's own stream."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.hostname or "").lower() not in ("radio.garden", "www.radio.garden"):
        return None
    match = _RADIO_GARDEN.match(parts.path)
    if not match:
        return None
    return f"https://radio.garden/api/ara/content/listen/{match.group(1)}/channel.mp3"


def _http_url(value: str, base: str = "") -> str | None:
    value = html.unescape(value.strip()).replace("\\/", "/")
    if not value or any(char in value for char in "\r\n\x00"):
        return None
    try:
        parts = urlsplit(urljoin(base, value))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        return urlunsplit(parts._replace(fragment=""))
    except ValueError:
        return None


def _script_links(text: str, base: str) -> list[str]:
    text = text.replace("\\/", "/")
    links = []
    for match in _URL_LITERAL.finditer(text):
        url = _http_url(match.group(1), base)
        if url and (
            _MEDIA_EXTENSION.search(url)
            or _STREAM_KEY.search(text[max(0, match.start() - 48) : match.start()])
        ):
            links.append(url)
    return links


def _page_links(text: str, base: str) -> list[str]:
    """Prefer audio and playlist URLs, then embedded players and listen pages."""
    soup = BeautifulSoup(text, "html.parser")
    base_tag = soup.find("base", href=True)
    if base_tag:
        base = _http_url(str(base_tag["href"]), base) or base
    media, players = [], []
    for tag in soup.find_all(["audio", "source", "iframe", "embed", "object", "a", "link", "meta"]):
        raw = tag.get("src") or tag.get("href") or tag.get("data")
        if tag.name == "meta" and str(tag.get("property", "")).startswith("og:audio"):
            raw = tag.get("content")
        if not isinstance(raw, str):
            continue
        url = _http_url(raw, base)
        if not url:
            continue
        if (
            tag.name in ("audio", "source")
            or _MEDIA_EXTENSION.search(url)
            or (tag.name == "meta" and tag.get("content") == raw)
        ):
            media.append(url)
        elif tag.name in ("iframe", "embed", "object") or _LISTEN.search(
            " ".join(
                [
                    tag.get_text(" ", strip=True),
                    raw,
                    str(tag.get("title", "")),
                    str(tag.get("aria-label", "")),
                ]
            )
        ):
            players.append(url)
    # Player configurations often expose a URL in data attributes or inline JSON.
    for tag in soup.find_all(True):
        for key in ("data-source", "data-stream", "data-stream-url", "data-audio", "data-url"):
            value = tag.get(key)
            if isinstance(value, str) and (url := _http_url(value, base)):
                media.append(url)
    for script in soup.find_all("script"):
        media.extend(_script_links(str(script.string or script.get_text()), base))
        # A linked player script can contain a static stream configuration.
        src = script.get("src")
        if isinstance(src, str) and _LISTEN.search(src) and (url := _http_url(src, base)):
            players.append(url)
    return list(dict.fromkeys(media + players))


def _json_links(value, base: str, audio_context: bool = False) -> list[str]:
    links = []
    if isinstance(value, dict):
        for key, child in value.items():
            context = audio_context or bool(re.search(r"audio|stream|source|playlist", key, re.I))
            links.extend(_json_links(child, base, context))
    elif isinstance(value, list):
        for child in value:
            links.extend(_json_links(child, base, audio_context))
    elif isinstance(value, str):
        if not value.startswith(("http://", "https://", "//", "/")) and not _MEDIA_EXTENSION.search(
            value
        ):
            return []
        url = _http_url(value, base)
        if url and (audio_context or _MEDIA_EXTENSION.search(url)):
            links.append(url)
    return list(dict.fromkeys(links))


def discover_streams(
    url: str,
    *,
    cancel: threading.Event | None = None,
    timeout: float = 25.0,
    max_requests: int = 16,
    max_depth: int = 4,
) -> DiscoveryResult:
    """Scan a bounded set of links, verifying responses before returning audio.

    Calls belong on a worker thread. Connections, response sizes, traversal,
    and elapsed time are bounded. Cancellation never needs to join that thread.
    Pages requiring JavaScript execution or a signed-in browser are not supported.
    """
    start_url = _http_url(url)
    if not start_url:
        raise ValueError("Enter a complete HTTP or HTTPS webpage or stream URL.")
    cancel = cancel or threading.Event()
    deadline = time.monotonic() + timeout
    pending = deque([(start_url, 0, start_url)])
    visited = set()
    found: dict[str, DiscoveredStream] = {}
    checked = 0
    first_error = ""
    limited = False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(get_proxies()))
    user_agent = get_user_agent("RadioMaster+ Stream Finder")
    request_timeout = min(5.0, max(0.1, get_timeout(default=5.0)))
    while pending and checked < max_requests:
        if cancel.is_set() or time.monotonic() >= deadline:
            limited = not cancel.is_set()
            break
        current, depth, source = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        request_url = _iono_playlist_url(current) or _radio_garden_url(current) or current
        checked += 1
        try:
            request = urllib.request.Request(
                request_url,
                headers={
                    "User-Agent": user_agent,
                    "Accept": "*/*",
                    "Referer": source,
                },
            )
            with opener.open(
                request, timeout=min(request_timeout, max(0.1, deadline - time.monotonic()))
            ) as response:
                final_url = response.geturl()
                content_type = (
                    (response.headers.get("Content-Type") or "").split(";")[0].lower().strip()
                )
                path = urlsplit(final_url).path.lower()
                playlist = content_type in _PLAYLIST_TYPES or path.endswith(
                    (".m3u", ".m3u8", ".pls", ".asx")
                )
                if content_type.startswith("audio/") and not playlist:
                    found[final_url] = DiscoveredStream(
                        final_url, content_type.removeprefix("audio/"), source
                    )
                    continue
                body = bytearray()
                # read1 avoids waiting for an entire buffer from a live stream.
                read = getattr(response, "read1", response.read)
                while len(body) < 262144 and not cancel.is_set() and time.monotonic() < deadline:
                    chunk = read(min(16384, 262144 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if content_type == "application/octet-stream" and len(body) >= 512:
                        break
                if len(body) == 262144:
                    limited = True
            if cancel.is_set():
                break
            text = body.decode("utf-8", "replace")
            if playlist and "#EXT-X-" in text:
                found[final_url] = DiscoveredStream(final_url, "HLS", source)
                continue
            links = []
            if playlist:
                if path.endswith(".asx") or content_type == "video/x-ms-asf":
                    xml = BeautifulSoup(text, "html.parser")
                    links = [str(tag["href"]) for tag in xml.find_all("ref", href=True)]
                else:
                    is_pls = content_type == "audio/x-scpls" or path.endswith(".pls")
                    for line in text.splitlines():
                        line = line.strip()
                        if is_pls and re.match(r"File\d+\s*=", line, re.I):
                            line = line.split("=", 1)[1].strip()
                        elif is_pls and re.match(
                            r"(?:NumberOfEntries|Version|Title\d+|Length\d+)\s*=", line, re.I
                        ):
                            continue
                        if line and not line.startswith(("#", "[")):
                            links.append(line)
            elif content_type == "application/json" or text.lstrip().startswith(("{", "[")):
                links = _json_links(json.loads(text), final_url)
            elif "javascript" in content_type:
                links = _script_links(text, final_url)
            elif content_type == "application/octet-stream" and (
                body.startswith((b"ID3", b"OggS", b"fLaC"))
                or (len(body) > 1 and body[0] == 255 and body[1] & 224 == 224)
            ):
                found[final_url] = DiscoveredStream(final_url, "audio", source)
            else:
                links = _page_links(text, final_url)
            for link in links:
                candidate = _http_url(link, final_url)
                if not candidate:
                    continue
                # iono.fm supplies placeholders intended for its JS player.
                if _iono_playlist_url(current):
                    parts = urlsplit(candidate)
                    query = [
                        (key, value)
                        for key, value in parse_qsl(parts.query)
                        if not re.fullmatch(r"<[^>]+>", value)
                    ]
                    candidate = urlunsplit(parts._replace(query=urlencode(query)))
                if depth < max_depth:
                    pending.append((candidate, depth + 1, final_url))
                elif candidate not in visited:
                    limited = True
        except Exception as exc:
            if checked == 1:
                first_error = str(exc)
    return DiscoveryResult(
        tuple(found.values()), checked, limited or bool(pending), cancel.is_set(), first_error
    )
