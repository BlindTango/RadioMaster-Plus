"""Track splitting service for splitting audio files into individual tracks."""

import subprocess
import os
import logging
import json
from typing import Any

logger = logging.getLogger("radiomaster")


from radiomaster.utils.tools import get_ffmpeg, get_ffprobe


class TrackSplitter:
    """Splits audio files (e.g., radio recordings, mixed DJ sets) into tracks."""

    @staticmethod
    def detect_silence(file_path: str, silence_duration: float = 2.0,
                       silence_threshold: float = -50.0) -> list[float]:
        """Detect silence periods in an audio file to find track boundaries."""
        try:
            cmd = [
                get_ffmpeg(), "-i", file_path, "-af",
                f"silencedetect=noise={silence_threshold}dB:d={silence_duration}",
                "-f", "null", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Parse silence end times (track boundaries)
            boundaries = []
            for line in result.stderr.split("\n"):
                if "silence_end:" in line:
                    try:
                        time_str = line.split("silence_end:")[1].strip().split()[0]
                        boundaries.append(float(time_str))
                    except (ValueError, IndexError):
                        continue
            return boundaries
        except Exception as e:
            logger.error(f"Silence detection failed: {e}")
            return []

    @staticmethod
    def split_by_silence(file_path: str, output_dir: str, prefix: str = "track",
                         silence_duration: float = 2.0,
                         silence_threshold: float = -50.0,
                         min_track_duration: float = 10.0) -> list[str]:
        """Split an audio file at silence boundaries into separate tracks."""
        boundaries = TrackSplitter.detect_silence(
            file_path, silence_duration, silence_threshold
        )
        if not boundaries:
            logger.warning("No silence boundaries detected")
            return []

        os.makedirs(output_dir, exist_ok=True)
        output_files = []
        start = 0.0
        # -c copy needs a container that matches the source codec -- forcing
        # .mp3 regardless of input format made this fail for anything that
        # wasn't already MP3 (e.g. WAV/FLAC recordings). Preserve the
        # source's own extension instead so the stream copy is always valid.
        ext = os.path.splitext(file_path)[1] or ".mp3"

        for i, end in enumerate(boundaries):
            duration = end - start
            if duration >= min_track_duration:
                output_path = os.path.join(output_dir, f"{prefix}_{i+1:02d}{ext}")
                cmd = [
                    get_ffmpeg(), "-i", file_path, "-ss", str(start),
                    "-to", str(end), "-c", "copy", "-y", output_path,
                ]
                try:
                    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                    output_files.append(output_path)
                except Exception as e:
                    logger.error(f"Failed to split track {i+1}: {e}")
            start = end

        # Handle the last segment
        if start > 0:
            output_path = os.path.join(output_dir, f"{prefix}_{len(boundaries)+1:02d}{ext}")
            cmd = [
                get_ffmpeg(), "-i", file_path, "-ss", str(start),
                "-c", "copy", "-y", output_path,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                output_files.append(output_path)
            except Exception as e:
                logger.error(f"Failed to split final track: {e}")

        return output_files

    @staticmethod
    def split_by_chapters(file_path: str, output_dir: str, prefix: str = "chapter") -> list[str]:
        """Split an audio file by chapter markers."""
        import subprocess
        import json
        import re

        try:
            # Get chapter info
            cmd = [get_ffprobe(), "-i", file_path, "-print_format", "json",
                   "-show_chapters", "-loglevel", "error"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            chapters = data.get("chapters", [])

            if not chapters:
                logger.warning("No chapters found")
                return []

            os.makedirs(output_dir, exist_ok=True)
            output_files = []
            ext = os.path.splitext(file_path)[1] or ".mp3"

            for i, chapter in enumerate(chapters):
                start = float(chapter["start_time"])
                end = float(chapter["end_time"])
                title = chapter.get("tags", {}).get("title", f"{prefix}_{i+1:02d}")
                safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)
                output_path = os.path.join(output_dir, f"{safe_title}{ext}")

                cmd = [
                    get_ffmpeg(), "-i", file_path, "-ss", str(start),
                    "-to", str(end), "-c", "copy", "-y", output_path,
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                output_files.append(output_path)

            return output_files

        except Exception as e:
            logger.error(f"Chapter splitting failed: {e}")
            return []
