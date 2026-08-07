"""General utility helpers for RadioMaster+."""

import re
from typing import Any


def format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    if seconds < 0 or not seconds:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_time(time_str: str) -> float:
    """Parse HH:MM:SS or MM:SS string to seconds."""
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def sanitize_filename(name: str) -> str:
    """Remove invalid filename characters."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def truncate(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
