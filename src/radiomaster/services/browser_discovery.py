"""Find streams a page only starts once its player runs, using a temporary browser.

Chrome or Edge is started muted, without the person's profile or logins, in a
throw-away folder and controlled through its local debugging port. The page is
loaded, any Play or Listen button is pressed, and every address the page
requests is recorded; the likely ones are then checked like any other
candidate. The browser is always closed and its folder deleted afterwards.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from radiomaster.services.stream_discovery import (
    DiscoveredStream,
    DiscoveryResult,
    _MEDIA_EXTENSION,
    _http_url,
    discover_streams,
)

_BROWSERS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
)
_HINT = re.compile(r"(?:stream|radio|live|audio|icecast|shoutcast|listen|hls|playlist|cast)", re.I)
_SKIP_HOST = re.compile(
    r"(?:google|gstatic|doubleclick|facebook|twitter|analytics|googletagmanager|cloudflare"
    r"|youtube|ytimg|fonts\.|cdnjs|jquery|bootstrapcdn|sentry|hotjar|adservice|scorecard)", re.I)
_STATIC = re.compile(r"\.(?:js|css|png|jpe?g|gif|svg|ico|woff2?|ttf|webp|json|html?)(?:$|\?)", re.I)

# Presses the page's own Play / Listen controls and starts any media element.
_PRESS_PLAY = r"""
(() => {
  let pressed = 0;
  const wanted = /(?:^|\b)(?:play|listen|live|start|tune ?in|ascolta|escuchar|écouter)(?:\b|$)/i;
  for (const el of document.querySelectorAll(
      'button,a,[role=button],[aria-label],[class*=play],[id*=play]')) {
    const text = [el.innerText, el.getAttribute('aria-label'), el.getAttribute('title'),
                  el.className && el.className.baseVal === undefined ? el.className : '',
                  el.id].join(' ');
    if (text.length < 120 && wanted.test(text) && pressed < 3) { try { el.click(); pressed++; } catch (e) {} }
  }
  for (const media of document.querySelectorAll('audio,video')) {
    try { media.muted = true; media.play(); } catch (e) {}
  }
  return pressed;
})()
"""


def find_browser() -> str | None:
    for template in _BROWSERS:
        path = os.path.expandvars(template)
        if os.path.isfile(path):
            return path
    return None


def candidate_urls(requests: dict[str, str], page_url: str) -> list[str]:
    """Addresses worth checking from a page's requests (url -> mime type)."""
    scored: dict[str, int] = {}
    for raw, mime in requests.items():
        url = _http_url(raw)
        if not url or url == page_url or _SKIP_HOST.search(urlsplit(url).netloc):
            continue
        mime = (mime or "").lower()
        if mime.startswith("audio/") or "mpegurl" in mime or "x-scpls" in mime:
            score = 3
        elif _MEDIA_EXTENSION.search(url):
            score = 2
        elif _STATIC.search(url) or mime.startswith(("image/", "font/", "text/css")):
            continue
        elif _HINT.search(url):
            score = 1
        else:
            continue
        scored[url] = max(score, scored.get(url, 0))
    return sorted(scored, key=lambda u: -scored[u])


class _DevTools:
    """Just enough of the Chrome DevTools protocol over a plain WebSocket."""

    def __init__(self, ws_url: str, timeout: float = 5.0):
        parts = urlsplit(ws_url)
        self._sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        self._sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = self._sock.recv(1024)
            if not chunk:
                raise OSError("The browser closed the debugging connection.")
            header += chunk
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise OSError("The browser refused the debugging connection.")
        self._buffer = header.split(b"\r\n\r\n", 1)[1]
        self._next_id = 0

    def send(self, method: str, params: dict | None = None) -> int:
        self._next_id += 1
        payload = json.dumps({"id": self._next_id, "method": method, "params": params or {}}).encode()
        mask = os.urandom(4)
        length = len(payload)
        head = b"\x81" + (bytes([0x80 | length]) if length < 126
                          else b"\xfe" + struct.pack(">H", length) if length < 65536
                          else b"\xff" + struct.pack(">Q", length))
        body = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(head + mask + body)
        return self._next_id

    def _read(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise OSError("The browser closed the debugging connection.")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def receive(self, timeout: float) -> dict | None:
        """Next protocol message, or None when nothing arrives in *timeout*."""
        self._sock.settimeout(max(0.05, timeout))
        message = b""
        try:
            while True:
                first, second = self._read(2)
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read(8))[0]
                payload = self._read(length)
                opcode = first & 0x0F
                if opcode == 8:
                    raise OSError("The browser closed the debugging connection.")
                if opcode in (1, 0):
                    message += payload
                    if first & 0x80:
                        return json.loads(message.decode("utf-8", "replace"))
        except socket.timeout:
            return None

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def _debug_port(folder: str, process: subprocess.Popen, deadline: float) -> int | None:
    path = os.path.join(folder, "DevToolsActivePort")
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return int(handle.readline().strip())
        except (OSError, ValueError):
            time.sleep(0.1)
    return None


def _page_socket(port: int, deadline: float) -> str | None:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
                for target in json.load(response):
                    if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                        return target["webSocketDebuggerUrl"]
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    return None


def find_with_browser(url: str, *, cancel: threading.Event | None = None,
                      seconds: float = 20.0, browser: str | None = None,
                      max_checks: int = 12) -> DiscoveryResult:
    """Load *url* in a temporary muted browser and return the audio streams it
    requested. Runs on a worker thread; cancelling closes the browser."""
    start = _http_url(url)
    if not start:
        raise ValueError("Enter a complete HTTP or HTTPS webpage URL.")
    cancel = cancel or threading.Event()
    browser = browser or find_browser()
    if not browser:
        return DiscoveryResult((), 0, error="Chrome or Edge is not installed.")
    folder = tempfile.mkdtemp(prefix="radiomaster-browser-")
    command = [
        browser, "--headless=new", "--mute-audio", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions", "--disable-sync",
        "--autoplay-policy=no-user-gesture-required", "--remote-debugging-port=0",
        f"--user-data-dir={folder}", "about:blank",
    ]
    process = None
    devtools = None
    requests: dict[str, str] = {}
    error = ""
    try:
        deadline = time.monotonic() + seconds
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        port = _debug_port(folder, process, time.monotonic() + 10)
        ws_url = _page_socket(port, time.monotonic() + 10) if port else None
        if not ws_url:
            error = "The browser did not start."
        else:
            devtools = _DevTools(ws_url)
            devtools.send("Network.enable")
            devtools.send("Page.enable")
            devtools.send("Page.navigate", {"url": start})
            pressed_at = time.monotonic() + 4.0
            presses = 0
            while time.monotonic() < deadline and not cancel.is_set():
                if presses < 3 and time.monotonic() >= pressed_at:
                    presses += 1
                    pressed_at = time.monotonic() + 3.0
                    devtools.send("Runtime.evaluate", {"expression": _PRESS_PLAY})
                message = devtools.receive(0.25)
                if not message:
                    continue
                params = message.get("params") or {}
                if message.get("method") == "Network.requestWillBeSent":
                    request_url = (params.get("request") or {}).get("url", "")
                    requests.setdefault(request_url, "")
                elif message.get("method") == "Network.responseReceived":
                    response = params.get("response") or {}
                    requests[response.get("url", "")] = response.get("mimeType", "")
    except OSError as exc:
        error = f"Could not use the browser: {exc}"
    finally:
        if devtools is not None:
            try:
                devtools.send("Browser.close")
            except OSError:
                pass
            devtools.close()
        if process is not None:
            _close(process)
        shutil.rmtree(folder, ignore_errors=True)
    if cancel.is_set():
        return DiscoveryResult((), 0, cancelled=True)
    found: dict[str, DiscoveredStream] = {}
    checked = 0
    for candidate in candidate_urls(requests, start)[:max_checks]:
        if cancel.is_set():
            break
        checked += 1
        try:
            result = discover_streams(candidate, cancel=cancel, timeout=8.0,
                                      max_requests=3, max_depth=1)
        except Exception:
            continue
        for stream in result.streams:
            found.setdefault(stream.url, DiscoveredStream(stream.url, stream.format, "Browser"))
    return DiscoveryResult(tuple(found.values()), checked, cancelled=cancel.is_set(), error=error)


def _close(process: subprocess.Popen) -> None:
    """End the browser and every helper process it started."""
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
