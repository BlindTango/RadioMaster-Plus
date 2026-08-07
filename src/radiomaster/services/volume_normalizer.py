"""Volume normalization service using EBU R128 / ReplayGain standards."""

import logging
from typing import Any

logger = logging.getLogger("radiomaster")


from radiomaster.utils.tools import get_ffmpeg


class VolumeNormalizer:
    """Analyzes and normalizes audio volume using EBU R128 / ReplayGain."""

    TARGETS = {
        "light": -18.0,
        "standard": -16.0,
        "loud": -14.0,
    }

    @staticmethod
    def analyze_loudness(file_path: str) -> dict[str, Any] | None:
        """Analyze loudness of an audio file using FFmpeg loudnorm filter."""
        import subprocess
        import json
        import re

        try:
            cmd = [
                get_ffmpeg(), "-i", file_path, "-af",
                "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json",
                "-f", "null", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Parse JSON from stderr
            stderr = result.stderr
            json_match = re.search(r"\{.*\}", stderr, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "input_i": data.get("input_i", 0),
                    "input_lra": data.get("input_lra", 0),
                    "input_tp": data.get("input_tp", 0),
                    "input_thresh": data.get("input_thresh", 0),
                    "target_offset": data.get("target_offset", 0),
                }
        except Exception as e:
            logger.error(f"Loudness analysis failed: {e}")
        return None

    @staticmethod
    def get_normalization_gain(loudness: float, target: str = "standard") -> float:
        """Calculate gain adjustment needed to reach target loudness."""
        target_lufs = VolumeNormalizer.TARGETS.get(target, -16.0)
        return target_lufs - loudness

    @staticmethod
    def build_normalization_filter(target: str = "standard", measured_i: float = 0.0,
                                    measured_lra: float = 0.0, measured_tp: float = 0.0,
                                    measured_thresh: float = 0.0, offset: float = 0.0) -> str:
        """Build an FFmpeg loudnorm filter string with measured parameters."""
        target_lufs = VolumeNormalizer.TARGETS.get(target, -16.0)
        return (
            f"loudnorm=I={target_lufs}:LRA=11:TP=-1.5:"
            f"measured_I={measured_i}:measured_LRA={measured_lra}:"
            f"measured_TP={measured_tp}:measured_thresh={measured_thresh}:"
            f"offset={offset}:print_format=summary"
        )
