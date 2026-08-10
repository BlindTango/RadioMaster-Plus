"""Download manager with queue, concurrent downloads, and progress tracking."""

import threading
import queue
import os
import logging
import subprocess
from typing import Any, Callable

logger = logging.getLogger("radiomaster")


from radiomaster.utils.tools import get_ffmpeg, get_ytdlp


class DownloadManager:
    """Manages download queue with concurrent execution."""

    def __init__(self, max_concurrent: int = 3) -> None:
        self._max_concurrent = max_concurrent
        self._queue: queue.Queue = queue.Queue()
        self._active: list[dict[str, Any]] = []
        self._paused: list[dict[str, Any]] = []
        self._running = False
        self._paused_flag = False
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

        self._on_progress: Callable[[int, float], None] | None = None
        self._on_complete: Callable[[int, str], None] | None = None
        self._on_error: Callable[[int, str], None] | None = None

    def start(self) -> None:
        """Start the download manager."""
        self._running = True
        self._paused_flag = False
        for _ in range(self._max_concurrent):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        """Stop the download manager."""
        self._running = False
        self._paused_flag = False

    def pause(self) -> None:
        """Pause all downloads. Active downloads continue but no new ones start."""
        self._paused_flag = True
        logger.info("Download manager paused")

    def resume(self) -> None:
        """Resume paused downloads."""
        self._paused_flag = False
        # Move paused items back to the queue
        with self._lock:
            for item in self._paused:
                self._queue.put(item)
            self._paused.clear()
        logger.info("Download manager resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused_flag

    def add_download(self, download_id: int, url: str, output_dir: str,
                     title: str = "", format: str = "best",
                     extract_audio: bool = False, audio_quality: str = "0",
                     filename_base: str = "") -> None:
        """Add a download to the queue.

        ``audio_quality`` is a yt-dlp ``--audio-quality`` value: "0" (the
        default) means best VBR; a bitrate like "192K" pins an exact rate.
        Only meaningful when ``extract_audio`` is set.

        ``filename_base`` (already filesystem-sanitized by the caller), if
        given, pins the output filename instead of yt-dlp's own
        ``%(title)s`` (drawn from the URL's own metadata, which for a
        podcast episode is not guaranteed to match the app's own episode
        title at all -- a generic MP3 URL often has no useful embedded
        title). Podcast downloads pass this so the show-notes file
        written alongside it (see podcast_panel.py's _on_download) is
        guaranteed to share the exact same base name as the audio file
        it documents, instead of the two drifting apart by whatever
        yt-dlp happened to extract.
        """
        self._queue.put({
            "id": download_id,
            "url": url,
            "output_dir": output_dir,
            "title": title,
            "format": format,
            "extract_audio": extract_audio,
            "audio_quality": audio_quality,
            "filename_base": filename_base,
        })

    def _worker(self) -> None:
        """Worker thread that processes downloads from the queue."""
        while self._running:
            if self._paused_flag:
                threading.Event().wait(1)
                continue
            try:
                item = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            self._execute_download(item)
            self._queue.task_done()

    # UI-facing quality labels aren't valid yt-dlp -f selectors on their own
    # (e.g. "1080p" needs to become a real format expression); map them here.
    _VIDEO_QUALITY_SELECTORS = {
        # "best" (the literal yt-dlp format name) selects only a single
        # pre-merged/progressive format -- on YouTube that tops out well
        # below the real best available quality (confirmed live: capped
        # at 360p on a video that actually has a 4K stream), since
        # anything above ~720p is served as separate video-only +
        # audio-only DASH streams that "best" can't see at all.
        # "bestvideo+bestaudio/best" is yt-dlp's own documented default
        # (what you get by passing no -f at all) -- picks the true best
        # available video and audio and merges them via ffmpeg, falling
        # back to a single combined format only if that's genuinely all
        # that's offered.
        "best": "bestvideo+bestaudio/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        "audio only": "bestaudio/best",
    }

    def _execute_download(self, item: dict[str, Any]) -> None:
        """Execute a single download."""
        download_id = item["id"]
        url = item["url"]
        output_dir = item["output_dir"]
        extract_audio = item.get("extract_audio", False)

        os.makedirs(output_dir, exist_ok=True)

        filename_base = item.get("filename_base") or "%(title)s"
        cmd = [get_ytdlp(), "--no-playlist", "-o", f"{output_dir}/{filename_base}.%(ext)s"]
        # RadioMaster+ bundles its own ffmpeg specifically so users don't
        # need one on their system -- but yt-dlp only looks on PATH by
        # default, so without this it silently can't find our bundled
        # copy on a machine that has no system-wide ffmpeg at all.
        # Confirmed live: with ffmpeg off PATH, a video quality selector
        # needing bestvideo+bestaudio merging (every quality option
        # except a raw progressive "best") produced two separate,
        # unmuxed video-only/audio-only files instead of one real video
        # -- "WARNING: You have requested merging of multiple formats
        # but ffmpeg is not installed. The formats won't be merged."
        # Also needed for audio extraction/transcoding (-x) and artwork
        # embedding, both of which shell out to ffmpeg too.
        cmd.extend(["--ffmpeg-location", get_ffmpeg()])
        from radiomaster.utils.network import get_yt_dlp_proxy_args
        cmd.extend(get_yt_dlp_proxy_args())
        if extract_audio:
            audio_format = item.get("format") or "mp3"
            audio_quality = item.get("audio_quality") or "0"
            cmd.extend(["-x", "--audio-format", audio_format, "--audio-quality", audio_quality])
        else:
            quality = item.get("format", "best")
            selector = self._VIDEO_QUALITY_SELECTORS.get(quality, quality)
            cmd.extend(["-f", selector])

        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        if config.get("downloads.embed_metadata", default=True):
            cmd.append("--embed-metadata")
        if config.get("downloads.embed_artwork", default=True):
            cmd.append("--embed-thumbnail")

        cmd.append(url)

        try:
            with self._lock:
                self._active.append(item)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            # Monitor progress, and remember the real output file path yt-dlp
            # reports -- without this, a completed download had no way to
            # be played back later (History had no idea what file it even
            # was). "[ExtractAudio] Destination: ..." (only printed when
            # extract_audio/-x post-processes the raw download into a
            # different file, e.g. remuxing to mp3) always wins over the
            # earlier "[download] Destination: ..." line when both appear,
            # since that's the actual final file on disk.
            destination_path = ""
            for line in process.stdout or []:
                stripped = line.strip()
                if "Destination:" in line:
                    candidate = line.split("Destination:", 1)[1].strip()
                    if candidate and (not destination_path or line.lstrip().startswith("[ExtractAudio]")):
                        destination_path = candidate
                elif stripped.startswith("[download]") and stripped.endswith("has already been downloaded"):
                    # yt-dlp found this exact file already on disk (a
                    # repeat download of the same episode/video, or
                    # re-downloading after a crash) and skipped
                    # re-fetching it entirely -- no "Destination:" line is
                    # ever printed in that case, so without this branch
                    # the file path was silently lost even though the
                    # file genuinely exists right where it's named. This
                    # was the actual reason file_path came back empty on
                    # a real repeat-download test.
                    candidate = stripped[len("[download]"):].rsplit(
                        "has already been downloaded", 1)[0].strip()
                    if candidate:
                        destination_path = candidate
                if "[download]" in line and "%" in line:
                    try:
                        percent_str = line.split("%")[0].split()[-1]
                        percent = float(percent_str)
                        if self._on_progress:
                            self._on_progress(download_id, percent)
                    except (ValueError, IndexError):
                        pass

            process.wait()

            if process.returncode == 0:
                if self._on_complete:
                    self._on_complete(download_id, destination_path)
            else:
                if self._on_error:
                    self._on_error(download_id, "Download failed")

        except Exception as e:
            logger.error(f"Download {download_id} failed: {e}")
            if self._on_error:
                self._on_error(download_id, str(e))
        finally:
            with self._lock:
                self._active = [a for a in self._active if a["id"] != download_id]

    def on_progress(self, cb: Callable[[int, float], None]) -> None:
        self._on_progress = cb

    def on_complete(self, cb: Callable[[int, str], None]) -> None:
        """*cb* receives (download_id, file_path) -- file_path is "" if
        yt-dlp's output never printed a recognizable Destination line."""
        self._on_complete = cb

    def on_error(self, cb: Callable[[int, str], None]) -> None:
        self._on_error = cb
