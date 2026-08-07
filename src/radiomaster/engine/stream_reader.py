"""Stream metadata reader for ICY/SHOUTcast streams."""

import requests
from typing import Any


class StreamReader:
    """Reads metadata from streaming audio sources.

    Supports HTTP/HTTPS (Icecast/SHOUTcast), HLS (``.m3u8``),
    DASH (``.mpd``), and UDP/RTP streams.
    """

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
                headers={"Icy-MetaData": "1"},
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
