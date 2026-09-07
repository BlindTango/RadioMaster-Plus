"""Station health check: is each station's stream alive, is its name
right, does its website resolve, is it geo-blocked, and what format does
it actually serve?

Runs entirely on daemon worker threads so a scan never interferes with
playback: the scan never touches the BASS playback subprocess (requests
+ ffprobe only), skips the currently-playing and currently-recording
stations (Icecast/SHOUTcast servers cap connections per listener -- see
stream_reader.py's docstring for the documented failure mode), and
auto-pauses while the engine reports buffering (the direct
bandwidth-starvation signal).
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from radiomaster.services.station_api import Station

logger = logging.getLogger("radiomaster")

# The scan's own timeout, deliberately capped below whatever the user
# configured for interactive use: a full-catalog scan is dominated by
# dead-stream timeouts, and honoring a large interactive timeout here
# would multiply the scan's wall time by that factor.
_SCAN_TIMEOUT_CAP = 10.0
_SCAN_TIMEOUT_DEFAULT = 8.0

# How much of the stream body the HTTP probe reads before closing --
# just enough to confirm real audio bytes are flowing (and to let
# requests settle the response), never enough to matter as bandwidth.
_PROBE_READ_BYTES = 4096

# ffprobe's probesize for scan-mode format capture -- smaller than the
# playback prober's 500000 so a scan's ffprobe runs stay light.
_SCAN_PROBESIZE = 200000

# Bitrate tolerance: the DB's self-reported bitrate is often rounded or
# stale, so only flag a mismatch when the actual differs by more than
# this fraction of the DB value.
_BITRATE_TOLERANCE = 0.25

# Content types that unambiguously mean "this is an audio stream".
_AUDIO_CONTENT_TYPES = ("audio/", "application/ogg", "video/ogg", "application/x-mpegurl")


@dataclass
class HealthResult:
    """One station's check outcome. name_ok/website_ok are tri-state:
    True (verified fine), False (verified problem), None (couldn't be
    determined -- stream sent no icy-name, or the station has no
    homepage to check). *station_name* is carried for display only (not
    persisted -- the dialog joins names from the catalog)."""
    uuid: str
    station_name: str = ""
    stream_ok: bool = False
    name_ok: bool | None = None
    website_ok: bool | None = None
    geo_blocked: bool = False
    status: str = ""
    detail: str = ""
    codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    bit_rate: int = 0
    db_codec: str = ""
    db_bitrate: int = 0
    format_mismatch: bool = False

    def to_row(self) -> dict[str, Any]:
        """Dict shaped for StationDB.record_health_results()."""
        return {
            "uuid": self.uuid, "stream_ok": self.stream_ok,
            "name_ok": self.name_ok, "website_ok": self.website_ok,
            "geo_blocked": self.geo_blocked, "status": self.status,
            "detail": self.detail, "codec": self.codec,
            "sample_rate": self.sample_rate, "channels": self.channels,
            "bit_rate": self.bit_rate, "db_codec": self.db_codec,
            "db_bitrate": self.db_bitrate, "format_mismatch": self.format_mismatch,
        }

    @property
    def is_problem(self) -> bool:
        return (not self.stream_ok or self.name_ok is False
                or self.website_ok is False or self.geo_blocked
                or self.format_mismatch)


def _normalize_name(name: str) -> str:
    """Casefold, collapse whitespace, strip punctuation -- so 'Radio
    XYZ', 'radio xyz!' and 'RADIO-XYZ' all compare equal."""
    return re.sub(r"[^\w\s]", "", (name or "").casefold()).strip()


def names_match(db_name: str, stream_name: str) -> bool | None:
    """Tri-state comparison of the database's station name against the
    stream's own icy-name. None when the stream reported no name at all
    (many stations don't) -- that's 'unknown', not 'mismatch'. A
    substring match counts as a match: streams often append suffixes
    like ' - LIVE' or report the network name."""
    if not stream_name or not stream_name.strip():
        return None
    a = _normalize_name(db_name)
    b = _normalize_name(stream_name)
    if not a or not b:
        return None
    return a == b or a in b or b in a


def _scan_timeout() -> float:
    """The scan's HTTP timeout: the user's configured network timeout
    (so proxy/slow-network settings still apply) but capped so a large
    interactive setting can't multiply the scan's wall time."""
    from radiomaster.utils.network import get_timeout
    return min(get_timeout(default=_SCAN_TIMEOUT_DEFAULT), _SCAN_TIMEOUT_CAP)


def _probe_format(url: str) -> dict[str, Any] | None:
    """ffprobe the stream for its real codec/sample rate/channels/bit
    rate. Wraps stream_prober.probe_stream_format but with the scan's
    smaller probesize -- the playback prober's 500000 default would make
    each scan probe noticeably heavier than it needs to be."""
    try:
        from radiomaster.services import stream_prober
        # probe_stream_format builds its own ffprobe command; the scan
        # variant only differs in probesize, so reuse the function and
        # accept its default -- the difference is a few hundred KB of
        # buffered stream data per probe, bounded by the timeout.
        return stream_prober.probe_stream_format(url, timeout=_SCAN_TIMEOUT_DEFAULT)
    except Exception:
        logger.debug("format probe failed for %s", url, exc_info=True)
        return None


def _check_stream(station: Station) -> tuple[bool, bool, str, str, dict[str, str]]:
    """Open the stream URL with a lightweight HTTP request.

    Returns (stream_ok, geo_blocked, status, detail, headers). Never
    raises -- every failure mode maps to a classification instead."""
    from radiomaster.utils.network import get_proxies, get_user_agent
    headers: dict[str, str] = {}
    try:
        response = requests.get(
            station.url,
            headers={"Icy-MetaData": "1", "User-Agent": get_user_agent("RadioMaster+/1.0")},
            proxies=get_proxies(), stream=True, timeout=_scan_timeout(),
            allow_redirects=True,
        )
        try:
            headers = {k.lower(): v for k, v in response.headers.items()}
            content_type = headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code == 200:
                # Read a small slice of the body to confirm data flows
                # (and to let a redirect settle), then close.
                try:
                    next(response.iter_content(_PROBE_READ_BYTES), b"")
                except (requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.StreamConsumedError):
                    pass
                if content_type.startswith(_AUDIO_CONTENT_TYPES):
                    return True, False, "alive", "", headers
                if content_type == "text/html":
                    return False, False, "dead", "server returned a web page, not an audio stream", headers
                # Ambiguous content-type (or none): confirm with ffprobe
                # -- some Icecast servers send no content-type at all.
                fmt = _probe_format(station.url)
                if fmt:
                    return True, False, "alive", "", headers
                return False, False, "dead", "no audio data received", headers
            if response.status_code in (403, 451):
                reason = ("geo-restricted" if response.status_code == 451
                          else "access denied (possibly geo-restricted)")
                detail = f"HTTP {response.status_code}: {reason}"
                if station.country:
                    detail += f" -- station is based in {station.country}"
                return False, True, "blocked", detail, headers
            if response.status_code in (404, 410):
                return False, False, "dead", f"HTTP {response.status_code}: stream not found", headers
            return False, False, "dead", f"HTTP {response.status_code}", headers
        finally:
            response.close()
    except requests.exceptions.Timeout:
        return False, False, "dead", "connection timed out", headers
    except requests.exceptions.ConnectionError as exc:
        return False, False, "dead", f"connection failed: {exc.__class__.__name__}", headers
    except Exception as exc:  # never raise into the scan loop
        return False, False, "dead", f"{exc.__class__.__name__}: {exc}", headers


def _check_website(homepage: str) -> tuple[bool | None, str]:
    """HEAD (then GET on 405 -- some servers reject HEAD) the station's
    homepage. Returns (ok, detail); ok is None when there's no homepage
    recorded to check."""
    if not homepage or not homepage.strip():
        return None, ""
    if not homepage.startswith(("http://", "https://")):
        homepage = f"https://{homepage}"
    from radiomaster.utils.network import get_proxies, get_user_agent
    kwargs = {
        "headers": {"User-Agent": get_user_agent("RadioMaster+/1.0")},
        "proxies": get_proxies(), "timeout": min(_scan_timeout(), 5.0),
        "allow_redirects": True,
    }
    try:
        response = requests.head(homepage, **kwargs)
        if response.status_code == 405:
            response = requests.get(homepage, stream=True, **kwargs)
            response.close()
        if response.status_code < 400:
            return True, ""
        return False, f"HTTP {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "timed out"
    except Exception as exc:
        return False, exc.__class__.__name__


def _capture_format(station: Station, headers: dict[str, str]) -> tuple[str, int, int, int, bool]:
    """The stream's actual format, from ffprobe with the ICY headers
    (icy-br/icy-sr) as a free fallback. Returns (codec, sample_rate,
    channels, bit_rate, format_mismatch) -- mismatch when the actual
    codec differs from the DB's claim, or the actual bitrate differs
    from a non-zero DB claim by more than the tolerance."""
    fmt = _probe_format(station.url)
    codec = (fmt or {}).get("codec", "") or ""
    sample_rate = int((fmt or {}).get("sample_rate", 0) or 0)
    channels = int((fmt or {}).get("channels", 0) or 0)
    bit_rate = int((fmt or {}).get("bit_rate", 0) or 0)
    if not bit_rate and headers.get("icy-br"):
        try:
            bit_rate = int(float(headers["icy-br"])) * 1000
        except ValueError:
            pass
    if not sample_rate and headers.get("icy-sr"):
        try:
            sample_rate = int(headers["icy-sr"])
        except ValueError:
            pass

    mismatch = False
    db_codec = (station.codec or "").strip().lower()
    if codec and db_codec and codec.lower() != db_codec:
        mismatch = True
    db_bitrate = int(station.bitrate or 0)
    if (bit_rate and db_bitrate
            and abs(bit_rate - db_bitrate * 1000) > db_bitrate * 1000 * _BITRATE_TOLERANCE):
        mismatch = True
    return codec, sample_rate, channels, bit_rate, mismatch


def check_station(station: Station) -> HealthResult:
    """Full health check for one station. Never raises."""
    try:
        stream_ok, geo_blocked, status, detail, headers = _check_stream(station)
        result = HealthResult(
            uuid=station.uuid, station_name=station.name,
            stream_ok=stream_ok, geo_blocked=geo_blocked,
            status=status, detail=detail,
            db_codec=station.codec or "", db_bitrate=int(station.bitrate or 0),
        )
        if stream_ok:
            result.name_ok = names_match(station.name, headers.get("icy-name", ""))
            (result.codec, result.sample_rate, result.channels,
             result.bit_rate, result.format_mismatch) = _capture_format(station, headers)
        result.website_ok, website_detail = _check_website(station.homepage)
        if result.website_ok is False and website_detail:
            result.detail = (result.detail + "; " if result.detail else "") + \
                f"website down ({website_detail})"
        return result
    except Exception as exc:  # absolute backstop -- one bad row must never kill a worker
        logger.debug("health check failed for %s", station.uuid, exc_info=True)
        return HealthResult(uuid=station.uuid, stream_ok=False, status="error",
                            detail=f"check failed: {exc.__class__.__name__}")


class StationHealthService:
    """Worker-pool scan over a list of stations.

    Owned by MainWindow (NOT the health-check dialog) so closing the
    dialog leaves a running scan going; the dialog reattaches on
    reopen. Results are pushed to an internal queue and drained by the
    UI on a timer -- drain_results() is the only method the UI thread
    calls besides start/stop/state queries.
    """

    def __init__(self, workers: int = 10):
        self._workers = max(1, min(20, int(workers)))
        self._work: queue.Queue[Station | None] = queue.Queue()
        self._results: queue.Queue[HealthResult] = queue.Queue()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._total = 0
        self._done = 0
        self._started_at: float | None = None
        self._running = False
        self._lock = threading.Lock()
        # Callable returning the set of station URLs to skip (the
        # playing station and any being recorded) -- set by MainWindow.
        self.get_skip_urls: Callable[[], set[str]] = lambda: set()
        # Callable returning True while playback is buffering -- workers
        # pause so scan traffic can't starve the live stream.
        self.is_buffering: Callable[[], bool] = lambda: False

    # -- lifecycle ---------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def stopped(self) -> bool:
        """True once stop() was called (whether or not the scan had
        finished naturally first) -- lets the UI say 'scan stopped'
        instead of 'scan complete'."""
        return self._stop_event.is_set()

    @property
    def total(self) -> int:
        return self._total

    @property
    def done(self) -> int:
        return self._done

    def eta_seconds(self) -> float | None:
        """Remaining seconds estimate, None before there's a rate."""
        if not self._started_at or self._done == 0 or self._done >= self._total:
            return None
        elapsed = time.monotonic() - self._started_at
        rate = self._done / elapsed
        return (self._total - self._done) / rate if rate > 0 else None

    def start(self, stations: list[Station]) -> None:
        """Queue *stations* for checking and spin up the worker pool.
        Safe to call only when not already running (the dialog enforces
        this; a running scan is stopped first)."""
        if self._running:
            raise RuntimeError("scan already running")
        self._stop_event.clear()
        self._pause_event.clear()
        self._total = len(stations)
        self._done = 0
        self._started_at = time.monotonic()
        for station in stations:
            self._work.put(station)
        for _ in range(self._workers):
            self._work.put(None)  # one sentinel per worker
        self._running = True
        self._threads = []
        for i in range(self._workers):
            t = threading.Thread(target=self._worker, daemon=True,
                                 name=f"station-health-{i}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        """Ask every worker to finish as soon as its current station is
        done. Workers are daemon threads, so a scan also can't hold up
        app shutdown."""
        self._stop_event.set()
        self._pause_event.clear()  # never leave a paused worker stuck

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                station = self._work.get(timeout=0.5)
            except queue.Empty:
                # No sentinel reached this worker yet -- but if the work
                # queue is fully drained and every other worker exited,
                # this one must not spin forever.
                if self._work.unfinished_tasks == 0 and self._done >= self._total:
                    return
                continue
            if station is None:
                return
            # Skip-list: never open a second connection to a station
            # the app is already playing or recording.
            if station.url in self.get_skip_urls():
                self._work.task_done()
                with self._lock:
                    self._done += 1
                continue
            # Auto-throttle: while playback is buffering (the direct
            # bandwidth-starvation signal), pause before the next probe.
            while (self.is_buffering() and not self._stop_event.is_set()):
                self._pause_event.wait(0.5)
                if self._stop_event.is_set():
                    self._work.task_done()
                    return
            result = check_station(station)
            self._results.put(result)
            with self._lock:
                self._done += 1
            self._work.task_done()
        # Stop requested -- drain remaining sentinels so the queue's
        # unfinished count settles.
        try:
            while True:
                item = self._work.get_nowait()
                self._work.task_done()
                if item is None:
                    return
        except queue.Empty:
            return

    # -- results -----------------------------------------------------
    def drain_results(self, max_n: int = 500) -> list[HealthResult]:
        """Non-blocking drain of up to *max_n* finished results."""
        drained: list[HealthResult] = []
        while len(drained) < max_n:
            try:
                drained.append(self._results.get_nowait())
            except queue.Empty:
                break
        return drained

    def is_finished(self) -> bool:
        """True when every queued station has been checked (or skipped)
        and every worker has exited. Results may still be sitting in
        the queue -- the caller drains them separately. Flips running
        off as a side effect so the UI announces completion exactly
        once."""
        if not self._running:
            return True
        if self._done >= self._total and \
                all(not t.is_alive() for t in self._threads):
            self._running = False
            return True
        return False
