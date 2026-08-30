"""yt-dlp wrapper for YouTube and video site extraction."""

import os
import subprocess
import json
import logging
from typing import Any

logger = logging.getLogger("radiomaster")


from radiomaster.utils.tools import get_ytdlp
from radiomaster.utils.network import get_yt_dlp_proxy_args

# yt-dlp.exe is a console-subsystem executable -- every subprocess.run()
# call here flashed a real console window on screen for the process's
# whole lifetime (a full 20-result search took long enough that the
# window was clearly visible, not just a flicker) because none of them
# suppressed it. Every ffmpeg/ffplay Popen() call elsewhere in this
# codebase already does this; yt-dlp's own calls never did.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


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
            subprocess.run([get_ytdlp(), "--version"], capture_output=True, timeout=15,
                          creationflags=_NO_WINDOW)
        except FileNotFoundError:
            logger.warning("yt-dlp not found. YouTube features will be unavailable.")
        except Exception as e:
            logger.warning(f"yt-dlp version check failed (continuing anyway): {e}")

    def get_stream_url(self, url: str) -> str | None:
        """Get a single playable stream URL for a video.

        -f "best[ext=mp4]/best" forces yt-dlp to pick ONE already-muxed
        format (falling back to whatever single-file format is
        available) -- without an explicit -f, yt-dlp's default selector
        is "bestvideo+bestaudio", and modern YouTube serves those as two
        SEPARATE adaptive streams (video-only + audio-only). -g then
        printed two URLs, one per line, and result.stdout.strip() handed
        that whole two-line blob to ffplay as if it were a single URL --
        which obviously isn't a valid stream, confirmed live as the
        actual cause of "cannot stream"/playback failing on every video.
        A single muxed format can't be split like that, so this always
        returns exactly one URL (or None).
        """
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-g", "--no-playlist",
                 "-f", "best[ext=mp4]/best", url],
                capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                lines = [line for line in result.stdout.strip().splitlines() if line]
                return lines[0] if lines else None
        except Exception as e:
            logger.error(f"Failed to get stream URL: {e}")
        return None

    def get_stream_info(self, url: str) -> dict[str, Any] | None:
        """Resolve a playable stream URL the same way get_stream_url()
        does, but also returns the HTTP headers (User-Agent above all)
        yt-dlp itself would have sent for that specific format, plus the
        title/duration -- all from the one -j call instead of get_stream_url()
        + a separate get_info() round trip.

        The headers matter, not just the URL: a googlevideo.com playback
        URL is bound to the request context yt-dlp resolved it under
        (confirmed live -- itag 18 resolved via the "ANDROID_VR" player
        client) and handing the bare URL to ffplay with ffplay's own
        default User-Agent got a flat "HTTP error 403 Forbidden" for some
        videos while others played fine, with no pattern visible from the
        app alone -- reproduced directly: the exact same URL 403'd
        without a User-Agent header and played immediately with one.
        Replaying yt-dlp's own headers on the actual playback request is
        what get_stream_url() alone could never do."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-j", "--no-playlist",
                 "-f", "best[ext=mp4]/best", url],
                capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
            )
            if result.returncode == 0 and result.stdout.strip():
                info = json.loads(result.stdout.strip().splitlines()[0])
                stream_url = info.get("url")
                if not stream_url:
                    return None
                return {
                    "url": stream_url,
                    "http_headers": info.get("http_headers") or {},
                    "title": info.get("title", ""),
                    "duration": float(info.get("duration") or 0.0),
                }
        except Exception as e:
            logger.error(f"Failed to get stream info: {e}")
        return None

    def get_info(self, url: str) -> dict[str, Any] | None:
        """Get video metadata."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-j", "--no-playlist", url],
                capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
        return None

    # YouTube's own search-results page filters results by type via an
    # "sp" query param (an opaque base64-encoded protobuf blob, not
    # something yt-dlp exposes a friendlier flag for) -- these three are
    # YouTube's own well-known values for "Type: Video/Channel/Playlist"
    # confirmed live against a real search (channel search correctly
    # returned channel entries with channel_id/subscriber counts, no
    # videos; playlist search returned playlist entries, no videos).
    _SEARCH_TYPE_FILTERS = {
        "video": None,  # no filter needed -- ytsearch: already means videos only
        "channel": "EgIQAg%253D%253D",
        "playlist": "EgIQAw%253D%253D",
    }

    def search(self, query: str, max_results: int = 20,
               search_type: str = "video") -> list[dict[str, Any]]:
        """Search YouTube using yt-dlp, filtered to videos, channels, or
        playlists (search_type).

        --flat-playlist is what makes a 20-result search actually fast:
        without it, yt-dlp does a FULL metadata extraction for every
        single result (a real network round-trip per video), which for
        20 results routinely took well over a minute -- confirmed live
        (30s wasn't even enough for it to finish). --flat-playlist uses
        just the search-results-page data, seconds instead of a minute
        plus, and still includes everything this panel's results list
        actually shows (title/duration/channel).

        Also no longer gated on returncode == 0: yt-dlp exits non-zero
        if EVEN ONE result among many fails (a deleted/region-blocked
        video is common in a real 20-result search) -- confirmed live,
        one bad video among 20 discarded all 19 good ones that had
        already been fetched and printed. Every line of stdout that
        parses as JSON is kept regardless of the overall exit code.

        Channel/playlist search goes through the search-results-page URL
        directly (with the "sp" type filter) rather than the "ytsearchN:"
        shorthand -- that shorthand always means video search specifically
        and has no type-filtered equivalent. --playlist-end caps results
        there instead, since the URL form doesn't take a result count.
        """
        import urllib.parse
        if search_type == "video" or search_type not in self._SEARCH_TYPE_FILTERS:
            target = f"ytsearch{max_results}:{query}"
            extra_args = ["--no-playlist"]
        else:
            search_url = (
                "https://www.youtube.com/results?search_query="
                f"{urllib.parse.quote(query)}&sp={self._SEARCH_TYPE_FILTERS[search_type]}"
            )
            target = search_url
            extra_args = ["--playlist-end", str(max_results)]
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), target,
                 "-j", *extra_args, "--flat-playlist"],
                capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
            )
            results = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if not results and result.returncode != 0:
                logger.error(f"YouTube search returned no results (exit {result.returncode}): "
                             f"{result.stderr.strip()[-300:]}")
            return results
        except Exception as e:
            logger.error(f"Failed to search YouTube: {e}")
        return []

    def get_channel_videos(self, channel_url: str, max_results: int = 30) -> list[dict[str, Any]]:
        """List a subscribed channel's most recent videos -- appending
        "/videos" is what points yt-dlp at the channel's uploads tab
        specifically instead of its (much slower to enumerate, and not
        what "browse this channel's videos" means) full tab set."""
        url = channel_url.rstrip("/")
        if not url.endswith("/videos"):
            url += "/videos"
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), url,
                 "-j", "--flat-playlist", "--playlist-end", str(max_results)],
                capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
            )
            entries = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if not entries and result.returncode != 0:
                logger.error(f"Channel video listing failed (exit {result.returncode}): "
                             f"{result.stderr.strip()[-300:]}")
            return entries
        except Exception as e:
            logger.error(f"Failed to list channel videos: {e}")
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
            subprocess.run(cmd, check=True, timeout=3600, creationflags=_NO_WINDOW)
            return True
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

    def get_playlist_entries(self, url: str) -> list[dict[str, Any]]:
        """Get entries from a playlist."""
        try:
            result = subprocess.run(
                [get_ytdlp(), *get_yt_dlp_proxy_args(), "-j", "--flat-playlist", url],
                capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
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

    def get_version(self) -> str:
        """Return the installed yt-dlp version string, or "" if it can't
        be determined (e.g. the binary is missing)."""
        try:
            result = subprocess.run(
                [get_ytdlp(), "--version"], capture_output=True, text=True,
                timeout=15, creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"Failed to get yt-dlp version: {e}")
        return ""

    def download_to_temp(self, url: str, progress_cb=None) -> str | None:
        """Prepare best-quality video/audio in a temporary playback file.

        Modern YouTube serves its highest-quality video and audio as
        separate adaptive streams. yt-dlp downloads the best of each and
        FFmpeg merges them without re-encoding, preserving the source
        resolution and audio bitrate. This is the primary YouTube playback
        path; a lower-quality pre-muxed stream is used only if this fails.

        Returns the temp file path on success, or None on failure. The
        caller owns the file and should delete it when playback ends.
        """
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        os.remove(tmp_path)  # let yt-dlp create the file itself
        cmd = [
            get_ytdlp(), *get_yt_dlp_proxy_args(),
            "-f", "bestvideo+bestaudio/best",
            "--concurrent-fragments", "4",
            "--merge-output-format", "mp4",
            "--no-playlist", "-o", tmp_path, url,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=3600, creationflags=_NO_WINDOW)
            if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                return tmp_path
        except Exception as e:
            logger.error(f"Failed to download video to temp: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return None

    def check_for_update(self) -> tuple[bool, str]:
        """Check whether a newer yt-dlp release is available, without
        downloading it.

        Returns ``(update_available, latest_version)``. ``update_available``
        is True only when the installed version is older than the latest
        stable release. On any failure (offline, rate-limited, missing
        binary) it returns ``(False, "")`` so a background check can fail
        silently -- the manual Help > Update YouTube Library is the
        fallback that surfaces real errors.
        """
        current = self.get_version()
        if not current:
            return False, ""
        try:
            import requests
            resp = requests.get(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                timeout=10,
                headers={"Accept": "application/vnd.github+json",
                         "User-Agent": "RadioMasterPlus-Updater"},
            )
            if resp.status_code != 200:
                return False, ""
            tag = resp.json().get("tag_name", "").lstrip("vV")
            if not tag:
                return False, ""
            # Compare dotted version tuples (e.g. "2026.08.19").
            def _parts(v: str) -> tuple:
                import re
                return tuple(int(p) for p in re.findall(r"\d+", v)) or (0,)
            if _parts(tag) > _parts(current):
                return True, tag
        except Exception:
            return False, ""
        return False, ""

    def update(self, progress_cb=None) -> tuple[bool, str]:
        """Update the bundled yt-dlp.exe to the latest stable release.

        The bundled binary is a standalone PyInstaller-built exe, so it
        can't self-update via ``-U`` (that only works for pip/wheel
        installs -- it errors with "You installed yt-dlp with pip or
        using the wheel from PyPi"). Instead this downloads the latest
        ``yt-dlp.exe`` from the official GitHub releases and atomically
        replaces the bundled copy in place.

        Returns ``(ok, message)``. On success *message* is the new
        version; on failure it's a human-readable error.
        """
        import tempfile
        from radiomaster.utils.tools import get_tools_dir

        tools_dir = get_tools_dir()
        target = os.path.join(tools_dir, "yt-dlp.exe")
        if not os.path.isdir(tools_dir):
            return False, "The tools folder could not be found."
        if not os.access(tools_dir, os.W_OK):
            return False, (
                "The tools folder is not writable. If RadioMaster+ is installed "
                "under Program Files, run it as administrator or reinstall to a "
                "user-writable location to update the YouTube library."
            )

        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        try:
            import requests
            resp = requests.get(url, timeout=30, stream=True)
            resp.raise_for_status()
        except Exception as e:
            return False, f"Could not download the update: {e}"

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        tmp_path = target + ".part"
        try:
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=262144):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
            if total and downloaded != total:
                raise OSError(f"Download incomplete ({downloaded} of {total} bytes).")
            os.replace(tmp_path, target)
        except OSError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False, f"Could not save the updated YouTube library: {exc}"

        new_version = self.get_version()
        return True, new_version or "updated"
