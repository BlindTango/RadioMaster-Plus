"""yt-dlp wrapper for YouTube and video site extraction."""

import subprocess
import json
import logging
from typing import Any

logger = logging.getLogger("radiomaster")


from radiomaster.utils.tools import get_ytdlp
from radiomaster.utils.network import get_yt_dlp_proxy_args


class YouTubeService:
    """Wrapper around yt-dlp for video/audio extraction and downloading.

    The original class name ``YouTubeDLService`` conflicted with the import in
    ``YouTubePanel`` (which expects ``YouTubeService``). Renaming the class
    resolves the import error and aligns with the rest of the codebase.
    """

    def __init__(self) -> None:
        self._check_available()

    def _check_available(self) -> None:
        """Check if yt-dlp is installed.

        Only ever logs a warning -- never raises. This used to catch
        FileNotFoundError alone, but yt-dlp.exe is itself a real
        PyInstaller-built onefile executable with its own cold-start
        overhead (self-extraction, plus antivirus scanning a freshly
        installed/updated binary), which can genuinely take longer than
        a tight timeout -- when it did, subprocess.TimeoutExpired went
        completely uncaught out of the constructor. Since YouTubeService()
        is instantiated fresh on every single search/download action (not
        once at startup), that meant ANY slow cold start turned into a
        user-visible "Search failed: Command [...] timed out after 5
        seconds" on the very next thing they tried, unrelated to whether
        the actual search/download itself would have worked fine.
        """
        try:
            subprocess.run([get_ytdlp(), "--version"], capture_output=True, timeout=15)
        except FileNotFoundError:
            logger.warning("yt-dlp not found. YouTube features will be unavailable.")
        except Exception as e:
            logger.warning(f"yt-dlp version check failed (continuing anyway): {e}")

    def get_stream_url(self, url: str) -> str | None:
        """Get the best stream URL for a video."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-g", "--no-playlist", url],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"Failed to get stream URL: {e}")
        return None

    def get_info(self, url: str) -> dict[str, Any] | None:
        """Get video metadata."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-j", "--no-playlist", url],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
        return None

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        """Search YouTube using yt-dlp."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), f"ytsearch{max_results}:{query}", "-j", "--no-playlist"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                results = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        results.append(json.loads(line))
                return results
        except Exception as e:
            logger.error(f"Failed to search YouTube: {e}")
        return []

    def download(self, url: str, output_dir: str, format: str = "best",
                 extract_audio: bool = False) -> bool:
        """Download a video or audio."""
        cmd = [get_ytdlp(), "--no-playlist", "-o", f"{output_dir}/%(title)s.%(ext)s"]
        if extract_audio:
            cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])
        else:
            cmd.extend(["-f", format])
        cmd.append(url)

        try:
            subprocess.run(cmd, check=True, timeout=3600)
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

    def get_playlist_entries(self, url: str) -> list[dict[str, Any]]:
        """Get entries from a playlist."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-j", "--flat-playlist", url],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                entries = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        entries.append(json.loads(line))
                return entries
        except Exception as e:
            logger.error(f"Failed to get playlist: {e}")
        return []
