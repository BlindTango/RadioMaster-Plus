"""Data models for RadioMaster+."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Station:
    """Radio station data model."""
    id: int = 0
    station_id: str = ""
    name: str = ""
    url: str = ""
    country: str = ""
    country_code: str = ""
    language: str = ""
    language_codes: str = ""
    genre: str = ""
    tags: str = ""
    bitrate: int = 0
    codec: str = ""
    votes: int = 0
    clicks: int = 0
    is_custom: bool = False


@dataclass
class Podcast:
    """Podcast subscription data model."""
    id: int = 0
    feed_url: str = ""
    title: str = ""
    description: str = ""
    author: str = ""
    artwork_url: str = ""
    website_url: str = ""
    is_custom: bool = False


@dataclass
class Episode:
    """Podcast episode data model."""
    id: int = 0
    podcast_id: int = 0
    guid: str = ""
    title: str = ""
    description: str = ""
    content_encoded: str = ""
    duration: int = 0
    published_date: str = ""
    audio_url: str = ""
    file_path: str = ""
    download_status: str = "none"
    play_position: float = 0.0
    is_played: bool = False


@dataclass
class Audiobook:
    """Audiobook data model."""
    id: int = 0
    title: str = ""
    author: str = ""
    narrator: str = ""
    duration: float = 0.0
    format: str = ""
    file_path: str = ""
    folder_path: str = ""
    cover_path: str = ""
    chapters: str = ""
    last_position: float = 0.0
    bookmarks: str = ""
    is_daisy: bool = False
    daisy_format: str = ""


@dataclass
class MediaFile:
    """Local media file data model."""
    id: int = 0
    file_path: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    format: str = ""
    bitrate: int = 0
    cover_path: str = ""
    last_position: float = 0.0


@dataclass
class Playlist:
    """Playlist data model."""
    id: int = 0
    name: str = ""
    description: str = ""


@dataclass
class Download:
    """Download queue item data model."""
    id: int = 0
    url: str = ""
    title: str = ""
    source_type: str = ""
    format: str = ""
    quality: str = ""
    file_path: str = ""
    status: str = "queued"
    progress: float = 0.0
    total_size: int = 0
    error: str = ""


@dataclass
class Schedule:
    """Recording schedule data model."""
    id: int = 0
    url: str = ""
    title: str = ""
    source_type: str = ""
    start_time: str = ""
    duration: int = 0
    recurrence: str = ""
    format: str = "auto"
    enabled: bool = True


@dataclass
class Recording:
    """Completed recording data model."""
    id: int = 0
    schedule_id: int = 0
    url: str = ""
    title: str = ""
    file_path: str = ""
    duration: float = 0.0
    format: str = ""
    size_bytes: int = 0


@dataclass
class Bookmark:
    """Audiobook bookmark data model."""
    id: int = 0
    audiobook_id: int = 0
    position: float = 0.0
    label: str = ""
