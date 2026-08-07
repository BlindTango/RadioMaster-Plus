"""Download manager with queue, concurrent downloads, and progress tracking."""

import threading
import queue
import os
import logging
import subprocess
from typing import Any, Callable

logger = logging.getLogger("radiomaster")


from radiomaster.utils.tools import get_ytdlp


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
        self._on_complete: Callable[[int], None] | None = None
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
                     extract_audio: bool = False) -> None:
        """Add a download to the queue."""
        self._queue.put({
            "id": download_id,
            "url": url,
            "output_dir": output_dir,
            "title": title,
            "format": format,
            "extract_audio": extract_audio,
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
        "best": "best",
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

        cmd = [get_ytdlp(), "--no-playlist", "-o", f"{output_dir}/%(title)s.%(ext)s"]
        from radiomaster.utils.network import get_yt_dlp_proxy_args
        cmd.extend(get_yt_dlp_proxy_args())
        if extract_audio:
            audio_format = item.get("format") or "mp3"
            cmd.extend(["-x", "--audio-format", audio_format, "--audio-quality", "0"])
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
            )

            # Monitor progress
            for line in process.stdout or []:
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
                    self._on_complete(download_id)
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

    def on_complete(self, cb: Callable[[int], None]) -> None:
        self._on_complete = cb

    def on_error(self, cb: Callable[[int, str], None]) -> None:
        self._on_error = cb
