"""Live-stream recording session: one continuous file, or auto-split into
one file per track using ICY in-band metadata.

Extracted from RadioPanel's manual Record button (the original, working
implementation) so SchedulerService's timed recordings get the exact same
split-track behavior instead of the bare `ffmpeg -c copy` single-file
recording it used to be stuck with -- confirmed live: a scheduled
recording never split at all regardless of Settings > Recordings >
"Split recordings into tracks", since the scheduler never looked at that
setting or watched ICY metadata in the first place.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from radiomaster.engine.stream_reader import StreamReader
from radiomaster.utils.tools import get_ffmpeg

logger = logging.getLogger("radiomaster")

# Maps a recording format to an output extension and ffmpeg audio codec.
# FLAC/WAV are lossless so quality (a bitrate) doesn't apply to them.
RECORDING_CODECS: dict[str, tuple[str, str]] = {
    "mp3": (".mp3", "libmp3lame"),
    "aac": (".aac", "aac"),
    "ogg": (".ogg", "libvorbis"),
    "flac": (".flac", "flac"),
    "wav": (".wav", "pcm_s16le"),
}

# Maps a probed source codec (ffprobe's codec_name -- see
# stream_prober.py) to an output extension and ffmpeg encoder, for
# "record in the station's original format" -- deliberately a separate
# table from RECORDING_CODECS since ffprobe's codec_name vocabulary
# doesn't match the user-facing "Recording Format" combo's values.
SOURCE_CODEC_MAP: dict[str, tuple[str, str]] = {
    "mp3": (".mp3", "libmp3lame"),
    "aac": (".aac", "aac"),
    "flac": (".flac", "flac"),
    "vorbis": (".ogg", "libvorbis"),
    "opus": (".opus", "libopus"),
    "alac": (".m4a", "alac"),
    "pcm_s16le": (".wav", "pcm_s16le"),
    "pcm_s24le": (".wav", "pcm_s24le"),
    "wmav2": (".wma", "wmav2"),
}
# Codecs that don't take a bitrate (constant, format-defined instead).
_LOSSLESS_CODECS = {"flac", "pcm_s16le", "pcm_s24le", "alac"}

_DECODE_SAMPLE_RATE = 44100
_DECODE_CHANNELS = 2
# See _on_title_changed's docstring for why acting on a title change
# isn't instant.
_SPLIT_SETTLE_SECONDS = 2.0
# Give up on a station's ICY metadata after this many *consecutive*
# failed connection attempts (a real drop/refusal, not a timed poll).
_MAX_ICY_CONSECUTIVE_FAILURES = 5


def parse_icy_song(song: str) -> tuple[str, str]:
    """Split an ICY StreamTitle value into (artist, title). "Artist -
    Title" is the overwhelming convention, but not guaranteed -- if
    there's no " - " separator, treat the whole string as the title."""
    if " - " in song:
        artist, _, title = song.partition(" - ")
        return artist.strip(), title.strip()
    return "", song.strip()


class RecordingSession:
    """One recording of a live stream URL, either as a single continuous
    file or split into per-track files (whichever *split_tracks* says at
    construction time -- matches the original manual-Record behavior of
    reading the setting once, at record-start, not live mid-session).

    Split mode: ONE ffmpeg process stays connected to the station for the
    whole session, decoding to raw PCM; each track gets its own local
    (no network) ffmpeg process encoding that PCM to a file. Splitting a
    track is then purely local -- close one encode process's stdin
    (clean EOF, proper container finalization) and start the next --
    instead of killing the in-progress network connection and opening a
    brand new one for every split, which can fail outright on a station
    that only allows one connection per listener.

    *on_segment_finalized(file_path, title)* fires once per finished
    file: once on stop() for a non-split session, or once per completed
    track (plus once more on stop() for whatever's still in progress)
    for a split session.
    """

    def __init__(self, station_url: str, station_name: str, output_dir: str,
                 rec_format: str = "mp3", quality: str = "320k",
                 add_metadata: bool = True, split_tracks: bool = False,
                 match_source: bool = False, source_format: Optional[dict] = None,
                 on_segment_finalized: Optional[Callable[[str, str], None]] = None) -> None:
        """*match_source*, when True and *source_format* (see
        stream_prober.probe_stream_format) names a codec this class
        knows how to target, records using the station's own real
        codec/sample-rate/channels/bitrate instead of transcoding down
        to *rec_format*/*quality* -- a lossless (e.g. FLAC) station then
        gets recorded losslessly instead of unconditionally squashed to
        MP3. Falls back to *rec_format*/*quality* if *source_format* is
        None or names a codec with no known ffmpeg encoder mapping
        (SOURCE_CODEC_MAP)."""
        self.station_url = station_url
        self.station_name = station_name
        self.rec_format = rec_format
        self.quality = quality
        self.add_metadata = add_metadata
        self.split_tracks = split_tracks
        self.on_segment_finalized = on_segment_finalized

        self.match_source = False
        self._source_sample_rate = _DECODE_SAMPLE_RATE
        self._source_channels = _DECODE_CHANNELS
        self._source_bit_rate: Optional[int] = None
        if match_source and source_format and source_format.get("codec"):
            mapped = SOURCE_CODEC_MAP.get(source_format["codec"])
            if mapped is not None:
                self.ext, self._codec = mapped
                self.match_source = True
                if source_format.get("sample_rate"):
                    self._source_sample_rate = source_format["sample_rate"]
                if source_format.get("channels"):
                    self._source_channels = source_format["channels"]
                self._source_bit_rate = source_format.get("bit_rate") or None
        if not self.match_source:
            self.ext, self._codec = RECORDING_CODECS.get(rec_format, (".mp3", "libmp3lame"))

        safe_station_name = re.sub(r'[<>:"/\\|?*]', "_", station_name).strip() or "station"
        self.station_dir = os.path.join(output_dir, safe_station_name)
        os.makedirs(self.station_dir, exist_ok=True)
        # Recorded to a fixed temp name and renamed once its real name is
        # known (on the next track change, or on stop()).
        self.temp_path = os.path.join(self.station_dir, f".recording_in_progress{self.ext}")

        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None  # non-split path
        self._decode_proc: Optional[subprocess.Popen] = None  # split path
        self._encode_proc: Optional[subprocess.Popen] = None  # split path
        self._last_song: Optional[str] = None
        self._pending_title: Optional[str] = None
        self._split_timer: Optional[threading.Timer] = None
        self._stopped = False

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self.split_tracks:
            self._decode_proc = self._start_decode_process()
            self._encode_proc = self._start_encode_segment(self.temp_path)
            threading.Thread(target=self._feed_decode_to_encode, daemon=True).start()
            threading.Thread(target=self._track_watcher, daemon=True).start()
        else:
            self._process = self._start_ffmpeg_segment(self.temp_path, song=None)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            if self._split_timer is not None:
                self._split_timer.cancel()
                self._split_timer = None
        if self.split_tracks:
            if self._decode_proc is not None:
                try:
                    self._decode_proc.terminate()
                    self._decode_proc.wait(timeout=5)
                except Exception:
                    try:
                        self._decode_proc.kill()
                    except Exception:
                        pass
            with self._lock:
                self._finalize_encode_segment()
        else:
            if self._process is not None:
                self._stop_ffmpeg_gracefully(self._process)
                self._finalize_current_segment()

    # ------------------------------------------------------------------
    # Non-split path
    # ------------------------------------------------------------------
    def _recording_ffmpeg_args(self, output_path: str, song: Optional[str]) -> list[str]:
        # match_source uses stream copy -- no re-encode at all, so the
        # recording is bit-for-bit the station's own broadcast (same
        # codec, bitrate, sample rate, channels) rather than a
        # transcoded approximation of it.
        codec_arg = "copy" if self.match_source else self._codec
        cmd = [get_ffmpeg(), "-y", "-i", self.station_url, "-c:a", codec_arg]
        if not self.match_source and self.rec_format in ("mp3", "aac", "ogg"):
            cmd += ["-b:a", "320k" if self.quality.lower() == "best" else self.quality]
        if self.add_metadata:
            artist, title = parse_icy_song(song) if song else ("", "")
            cmd += ["-metadata", f"title={title or self.station_name}",
                    "-metadata", f"artist={artist or self.station_name}"]
        cmd.append(output_path)
        return cmd

    def _start_ffmpeg_segment(self, output_path: str, song: Optional[str]) -> subprocess.Popen:
        """stdin is a pipe (not DEVNULL) so it can be told to quit
        gracefully -- see _stop_ffmpeg_gracefully."""
        cmd = self._recording_ffmpeg_args(output_path, song)
        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    @staticmethod
    def _stop_ffmpeg_gracefully(process: subprocess.Popen, timeout: float = 5.0) -> None:
        """ffmpeg's documented graceful-quit is 'q' on stdin -- it then
        finalizes and closes the output file itself instead of being cut
        off mid-write."""
        try:
            if process.stdin:
                process.stdin.write(b"q")
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=timeout)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                process.kill()

    @staticmethod
    def _unique_path(path: str) -> str:
        """Appends " (2)", " (3)", ... if *path* already exists -- the
        same song can legitimately play twice in one recording session."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

    def _finalize_segment_path(self, song: Optional[str]) -> str:
        """The just-finished segment's real filename: "Artist - Title"
        from ICY metadata when known, falling back to a timestamp when
        the station never sent usable metadata for that segment."""
        if song:
            artist, title = parse_icy_song(song)
            base_name = f"{artist} - {title}" if artist and title else (title or self.station_name)
        else:
            base_name = f"{self.station_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        safe = re.sub(r'[<>:"/\\|?*]', "_", base_name).strip() or "track"
        return self._unique_path(os.path.join(self.station_dir, f"{safe}{self.ext}"))

    def _finalize_current_segment(self) -> None:
        temp_path = self.temp_path
        if os.path.exists(temp_path):
            final_path = self._finalize_segment_path(self._last_song)
            try:
                os.replace(temp_path, final_path)
            except OSError as e:
                logger.error(f"Could not finalize recording segment {temp_path}: {e}")
                return
            if self.on_segment_finalized:
                self.on_segment_finalized(final_path, self._last_song or "")

    # ------------------------------------------------------------------
    # Split-track path
    # ------------------------------------------------------------------
    def _start_decode_process(self) -> subprocess.Popen:
        """The one network connection for the whole session. -reconnect
        lets ffmpeg itself recover from a transient drop without this
        class needing to notice and restart anything (the per-segment
        encode processes never touch the network at all).

        Splitting a compressed bitstream at an arbitrary byte offset
        would produce a corrupted/clickable boundary, so even in
        match_source mode this still decodes to raw PCM -- but at the
        station's own real sample rate/channel count (not a hardcoded
        44.1kHz/stereo) so the PCM->re-encode roundtrip doesn't quietly
        resample or downmix a station that isn't already 44.1kHz
        stereo."""
        cmd = [
            get_ffmpeg(), "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", self.station_url,
            "-vn", "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", str(self._source_channels), "-ar", str(self._source_sample_rate),
            "pipe:1",
        ]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def _start_encode_segment(self, output_path: str) -> subprocess.Popen:
        """One track's local encode process: raw PCM in via stdin (fed by
        _feed_decode_to_encode), the real configured (or, in
        match_source mode, the station's own) format/quality out.
        Closing stdin is a clean EOF that makes ffmpeg finish encoding
        and exit on its own."""
        cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", str(self._source_sample_rate), "-ac", str(self._source_channels),
            "-i", "pipe:0", "-c:a", self._codec,
        ]
        if self.match_source:
            if self._codec not in _LOSSLESS_CODECS and self._source_bit_rate:
                cmd += ["-b:a", f"{self._source_bit_rate // 1000}k"]
        elif self.rec_format in ("mp3", "aac", "ogg"):
            cmd += ["-b:a", "320k" if self.quality.lower() == "best" else self.quality]
        cmd.append(output_path)
        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def _feed_decode_to_encode(self) -> None:
        """Pumps raw PCM from the session's one decode process into
        whichever encode process is current -- self._lock guards against
        a split (which replaces self._encode_proc) landing a write on
        the just-finalized process's already-closed stdin."""
        decode_proc = self._decode_proc
        try:
            while True:
                chunk = decode_proc.stdout.read(8192)
                if not chunk:
                    return  # decode process ended -- station dropped, or stop() killed it
                with self._lock:
                    if self._stopped:
                        return
                    encode_proc = self._encode_proc
                    if encode_proc is None or encode_proc.stdin is None:
                        continue
                    try:
                        encode_proc.stdin.write(chunk)
                    except (BrokenPipeError, OSError):
                        pass
        except Exception as e:
            logger.error(f"Recording feed loop for {self.station_name} ended: {e}")

    def _finalize_encode_segment(self) -> None:
        """Caller holds self._lock."""
        encode_proc = self._encode_proc
        if encode_proc is not None:
            try:
                if encode_proc.stdin:
                    encode_proc.stdin.close()
                encode_proc.wait(timeout=10)
            except Exception:
                try:
                    encode_proc.terminate()
                    encode_proc.wait(timeout=3)
                except Exception:
                    encode_proc.kill()
        temp_path = self.temp_path
        if os.path.exists(temp_path):
            final_path = self._finalize_segment_path(self._last_song)
            try:
                os.replace(temp_path, final_path)
            except OSError as e:
                logger.error(f"Could not finalize recording segment {temp_path}: {e}")
                return
            if self.on_segment_finalized:
                self.on_segment_finalized(final_path, self._last_song or "")

    def _split_segment(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._finalize_encode_segment()
            if self._stopped:
                return
            try:
                self._encode_proc = self._start_encode_segment(self.temp_path)
            except Exception as e:
                logger.error(f"Could not start next recording segment: {e}")

    def _on_title_changed(self, title: str) -> None:
        """FFmpeg's own decode buffering means a title change is seen on
        the ICY metadata connection a bit BEFORE the matching audio
        actually reaches the encode side -- splitting immediately on the
        change cuts the boundary too early. Settling for a short delay
        first lets decode catch up, so the split lands much closer to
        the real boundary. Comparing against pending_title (not
        last_song, which only updates once a split actually applies)
        means a station that resends the same StreamTitle on every
        metadata block doesn't endlessly cancel/restart this timer."""
        if title == self._pending_title:
            return
        self._pending_title = title
        old_timer = self._split_timer
        if old_timer is not None:
            old_timer.cancel()
        timer = threading.Timer(_SPLIT_SETTLE_SECONDS, self._apply_settled_split, args=(title,))
        timer.daemon = True
        self._split_timer = timer
        timer.start()

    def _apply_settled_split(self, title: str) -> None:
        if self._stopped or title != self._pending_title:
            return  # stopped, or superseded by a newer title while settling
        if self._last_song is None:
            # First title seen for this session -- the segment that's
            # already recording just learns its own name.
            self._last_song = title
            return
        self._split_segment()
        self._last_song = title

    def _track_watcher(self) -> None:
        """Watches ICY metadata over a SECOND connection to the station,
        independent of the session's one decode connection -- some
        stations only allow it intermittently, so a hiccup here
        reconnects instead of permanently killing split detection for
        the rest of the session."""
        consecutive_failures = 0

        def _still_recording() -> bool:
            return not self._stopped

        while _still_recording():
            response, meta_interval = StreamReader.open_icy_stream(self.station_url, timeout=15)
            if response is None or meta_interval <= 0:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                consecutive_failures += 1
                if consecutive_failures >= _MAX_ICY_CONSECUTIVE_FAILURES:
                    logger.warning(f"Giving up on ICY metadata for {self.station_url} after "
                                    f"{consecutive_failures} failed attempts")
                    return
                time.sleep(min(30, 2 ** consecutive_failures))
                continue
            consecutive_failures = 0
            try:
                while _still_recording():
                    try:
                        song = StreamReader.read_next_icy_song(response, meta_interval)
                    except Exception:
                        break  # connection dropped mid-stream -- fall through to reconnect
                    if not _still_recording():
                        return
                    if song:
                        self._on_title_changed(song)
            finally:
                try:
                    response.close()
                except Exception:
                    pass
            if _still_recording():
                time.sleep(2)  # brief pause before reconnecting after a live drop
