"""Stream metadata reader for ICY/SHOUTcast streams."""

import re
import requests
from typing import Any, Optional

# python-requests' default User-Agent ("python-requests/2.x") is a common
# bot-blocklist signature -- some Icecast/SHOUTcast servers silently refuse
# or throttle it while happily accepting ffmpeg's own connection (its
# default UA looks like a normal player, e.g. "Lavf/60.x"). That made the
# ICY metadata connection specifically (not the actual playback/recording
# connection, which goes through ffmpeg) fail or hang on some real stations
# even though nothing about our request was otherwise wrong. Confirmed
# against a reference implementation (see D:\Projects\RadioMaster) that
# sends an explicit UA for exactly this reason.
ICY_USER_AGENT = "RadioMaster+/1.0"


class StreamReader:
    """Reads metadata from streaming audio sources.

    Supports HTTP/HTTPS (Icecast/SHOUTcast), HLS (``.m3u8``),
    DASH (``.mpd``), and UDP/RTP streams.
    """

    @staticmethod
    def open_icy_stream(url: str, timeout: int = 10) -> tuple[Optional["requests.Response"], int]:
        """Opens ONE persistent HTTP connection with ICY metadata
        requested, for repeated calls to read_next_icy_song() as the
        station updates its metadata -- instead of every poller (Now
        Playing in RadioPanel, the recording track-split watcher) each
        opening and closing a brand new connection to the station every
        few seconds, forever, for as long as the station plays.

        That reconnect churn was real: a second (sometimes third, if
        recording the same station being listened to) full TCP/TLS
        connection being torn down and re-established every 8 seconds,
        indefinitely, right alongside the actual playback connection --
        competing for the same limited bandwidth, and on some Icecast/
        SHOUTcast servers (which often cap concurrent connections per
        listener or total listener slots) able to make the server itself
        drop or throttle the real playback connection. That reads exactly
        like "the stream keeps breaking/stuttering" during ordinary
        listening, worst-case rhythmically every ~8s -- not a decode bug
        at all, but self-inflicted connection pressure from polling.

        Returns (response, meta_interval); meta_interval is 0 if the
        station didn't advertise icy-metaint, meaning there's no
        metadata to poll at all (caller should give up rather than loop
        forever getting nothing).
        """
        try:
            response = requests.get(
                url, headers={"Icy-MetaData": "1", "User-Agent": ICY_USER_AGENT},
                stream=True, timeout=timeout,
            )
        except Exception:
            return None, 0
        meta_int = response.headers.get("icy-metaint", "0")
        try:
            meta_interval = int(meta_int)
        except ValueError:
            meta_interval = 0
        return response, meta_interval

    @staticmethod
    def read_next_icy_song(response: "requests.Response", meta_interval: int) -> Optional[str]:
        """Reads (and discards) meta_interval bytes of audio, then the
        metadata block right after it, from an already-open response (see
        open_icy_stream) -- the standard ICY in-band metadata framing.
        Returns the StreamTitle text if this block carried one, else
        None. Raises on a genuine I/O error (connection dropped) so the
        caller can decide whether to reopen; the read itself blocks
        naturally at the station's real bitrate, so this doesn't need an
        artificial sleep between calls the way reopening a fresh request
        every N seconds did."""
        if meta_interval <= 0:
            return None
        response.raw.read(meta_interval)
        meta_length_byte = response.raw.read(1)
        if not meta_length_byte:
            return None
        length = int.from_bytes(meta_length_byte, "big") * 16
        if length <= 0:
            return None
        meta_data = response.raw.read(length)
        meta_str = meta_data.decode("utf-8", errors="replace")
        if "StreamTitle=" in meta_str:
            match = re.search(r"StreamTitle='([^']*)'", meta_str)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def get_icy_metadata(url: str, timeout: int = 5) -> dict[str, Any]:
        """Fetch ICY stream metadata (station name, current song).

        Also detects HLS, DASH, and UDP/RTP streams and returns
        appropriate protocol metadata.
        """
        metadata: dict[str, Any] = {
            "name": "",
            "genre": "",
            "bitrate": 0,
            "current_song": "",
            "description": "",
            "protocol": "",
        }

        # Detect HLS streams
        if url.endswith(".m3u8") or "m3u8" in url.lower():
            metadata["name"] = "HLS Stream"
            metadata["protocol"] = "HLS"
            return metadata

        # Detect DASH streams
        if url.endswith(".mpd") or "mpd" in url.lower():
            metadata["name"] = "DASH Stream"
            metadata["protocol"] = "DASH"
            return metadata

        # Detect UDP/RTP streams
        if url.startswith("udp://") or url.startswith("rtp://"):
            metadata["name"] = "UDP/RTP Stream"
            metadata["protocol"] = "UDP/RTP"
            return metadata

        try:
            response = requests.get(
                url,
                headers={"Icy-MetaData": "1", "User-Agent": ICY_USER_AGENT},
                stream=True,
                timeout=timeout,
            )
            # Read headers
            metadata["name"] = response.headers.get("icy-name", "")
            metadata["genre"] = response.headers.get("icy-genre", "")
            bitrate_str = response.headers.get("icy-br", "0")
            try:
                metadata["bitrate"] = int(bitrate_str)
            except ValueError:
                pass
            metadata["description"] = response.headers.get("icy-description", "")
            metadata["protocol"] = "HTTP/HTTPS"

            # Read stream metadata if available
            meta_int = response.headers.get("icy-metaint", "0")
            try:
                meta_interval = int(meta_int)
            except ValueError:
                meta_interval = 0

            if meta_interval > 0:
                # Read first metadata block
                response.raw.read(meta_interval)
                meta_length = response.raw.read(1)
                if meta_length:
                    length = int.from_bytes(meta_length, "big") * 16
                    if length > 0:
                        meta_data = response.raw.read(length)
                        try:
                            meta_str = meta_data.decode("utf-8", errors="replace")
                            if "StreamTitle=" in meta_str:
                                import re
                                match = re.search(r"StreamTitle='([^']*)'", meta_str)
                                if match:
                                    metadata["current_song"] = match.group(1)
                        except Exception:
                            pass

            response.close()
        except Exception:
            pass

        return metadata
