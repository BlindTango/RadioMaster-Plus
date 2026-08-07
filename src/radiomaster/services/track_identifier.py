"""Track identification service using AcoustID, MusicBrainz, and Deezer."""

import logging
from typing import Any

logger = logging.getLogger("radiomaster")


class TrackIdentifier:
    """Identifies tracks using AcoustID fingerprinting and MusicBrainz/Deezer lookup."""

    def __init__(self) -> None:
        self._api_key = ""  # User must configure

    def set_api_key(self, key: str) -> None:
        """Set the AcoustID API key."""
        self._api_key = key

    def fingerprint(self, audio_file: str) -> str | None:
        """Generate an AcoustID fingerprint for an audio file."""
        try:
            import acoustid
            if not self._api_key:
                logger.warning("AcoustID API key not configured")
                return None
            results = acoustid.match(self._api_key, audio_file)
            if results:
                return results[0][1]  # Return the fingerprint
        except ImportError:
            logger.warning("pyacoustid not installed")
        except Exception as e:
            logger.error(f"Fingerprinting failed: {e}")
        return None

    def lookup_musicbrainz(self, fingerprint: str, duration: int) -> list[dict[str, Any]]:
        """Look up a fingerprint in MusicBrainz."""
        try:
            import musicbrainzngs
            musicbrainzngs.set_useragent("RadioMaster+", "1.0", "https://radiomaster.app")
            result = musicbrainzngs.get_recordings_from_fingerprint(
                {"fingerprint": fingerprint, "duration": duration}
            )
            recordings = []
            for recording in result.get("recordings", []):
                recordings.append({
                    "id": recording.get("id", ""),
                    "title": recording.get("title", ""),
                    "artist": recording.get("artist-credit", [{}])[0].get("name", "")
                    if recording.get("artist-credit") else "",
                    "album": recording.get("release-list", [{}])[0].get("title", "")
                    if recording.get("release-list") else "",
                })
            return recordings
        except ImportError:
            logger.warning("musicbrainzngs not installed")
        except Exception as e:
            logger.error(f"MusicBrainz lookup failed: {e}")
        return []

    def lookup_deezer(self, artist: str, title: str) -> dict[str, Any] | None:
        """Look up track metadata on Deezer."""
        try:
            import requests
            resp = requests.get(
                "https://api.deezer.com/search",
                params={"q": f"{artist} {title}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data"):
                    track = data["data"][0]
                    return {
                        "title": track.get("title", ""),
                        "artist": track.get("artist", {}).get("name", ""),
                        "album": track.get("album", {}).get("title", ""),
                        "duration": track.get("duration", 0),
                        "preview": track.get("preview", ""),
                    }
        except Exception as e:
            logger.error(f"Deezer lookup failed: {e}")
        return None

    def identify(self, audio_file: str) -> dict[str, Any] | None:
        """Identify a track by fingerprinting and metadata lookup.

        Uses AcoustID for fingerprinting, then MusicBrainz for metadata.
        Falls back to Deezer if AcoustID/MusicBrainz are unavailable.

        Args:
            audio_file: Path to the audio file to identify

        Returns:
            Dictionary with title, artist, album, source keys, or None
        """
        # Step 1: Generate fingerprint
        fingerprint = self.fingerprint(audio_file)
        if fingerprint:
            # Step 2: Look up in MusicBrainz
            import mutagen
            try:
                af = mutagen.File(audio_file)
                duration = int(af.info.length) if af and hasattr(af.info, 'length') else 0
            except Exception:
                duration = 0

            recordings = self.lookup_musicbrainz(fingerprint, duration)
            if recordings:
                rec = recordings[0]
                return {
                    "title": rec.get("title", ""),
                    "artist": rec.get("artist", ""),
                    "album": rec.get("album", ""),
                    "source": "musicbrainz",
                }

        # Step 3: Fallback to Deezer using filename-based artist/title
        import os
        filename = os.path.splitext(os.path.basename(audio_file))[0]
        # Try to parse "Artist - Title" pattern
        if " - " in filename:
            parts = filename.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            result = self.lookup_deezer(artist, title)
            if result:
                result["source"] = "deezer"
                return result

        return None
