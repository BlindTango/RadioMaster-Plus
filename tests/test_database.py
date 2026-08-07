"""Tests for the database layer."""

import pytest
import os
import tempfile
from radiomaster.database.connection import DatabaseManager
from radiomaster.database.migrations import run_migrations
from radiomaster.database.repository import (
    StationRepository,
    PodcastRepository,
    AudiobookRepository,
    MediaRepository,
    PlaylistRepository,
    DownloadRepository,
    ScheduleRepository,
)


@pytest.fixture
def db() -> DatabaseManager:
    """Create a temporary database for testing."""
    tmp_dir = tempfile.mkdtemp()
    db_manager = DatabaseManager(tmp_dir)
    db_manager.initialize()
    yield db_manager
    db_manager.close()


class TestDatabase:
    """Test database initialization and migrations."""

    def test_migrations_run(self, db: DatabaseManager) -> None:
        """Test that all migrations run successfully."""
        version = db.fetchone("SELECT MAX(version) as v FROM schema_version")
        assert version is not None
        assert version["v"] == 21  # 21 migrations

    def test_insert_station(self, db: DatabaseManager) -> None:
        """Test inserting a station."""
        repo = StationRepository(db)
        repo.bulk_upsert([{
            "id": "test123",
            "name": "Test Radio",
            "url": "http://test.stream/audio",
            "country": "United States",
            "language": "English",
            "bitrate": 128,
            "codec": "MP3",
        }])
        result = db.fetchone("SELECT * FROM stations WHERE station_id = ?", ("test123",))
        assert result is not None
        assert result["name"] == "Test Radio"

    def test_search_stations(self, db: DatabaseManager) -> None:
        """Test searching stations."""
        repo = StationRepository(db)
        repo.bulk_upsert([{
            "id": "search1", "name": "Rock Radio", "url": "http://rock.stream/audio",
            "country": "USA", "language": "English",
        }])
        results = repo.search("Rock")
        assert len(results) >= 1

    def test_custom_station(self, db: DatabaseManager) -> None:
        """Test adding a custom station."""
        repo = StationRepository(db)
        repo.add_custom("My Station", "http://my.stream/audio", genre="Test")
        stations = repo.get_custom_stations()
        assert len(stations) >= 1
        assert stations[0]["name"] == "My Station"


class TestPlaylist:
    """Test playlist operations."""

    def test_create_playlist(self, db: DatabaseManager) -> None:
        """Test creating a playlist."""
        repo = PlaylistRepository(db)
        playlist_id = repo.create("Test Playlist", "A test playlist")
        assert playlist_id > 0

    def test_add_item(self, db: DatabaseManager) -> None:
        """Test adding items to a playlist."""
        repo = PlaylistRepository(db)
        playlist_id = repo.create("Test Playlist")
        repo.add_item(playlist_id, "audio", "Test Track", item_url="http://test/audio.mp3")
        items = repo.get_items(playlist_id)
        assert len(items) == 1
        assert items[0]["title"] == "Test Track"


class TestPodcast:
    """Test podcast operations."""

    def test_add_podcast(self, db: DatabaseManager) -> None:
        """Test adding a podcast subscription."""
        repo = PodcastRepository(db)
        repo.add("http://test/feed.xml", "Test Podcast", "A test podcast",
                 "Test Author", is_custom=True)
        podcasts = repo.get_all()
        assert len(podcasts) >= 1
        assert podcasts[0]["title"] == "Test Podcast"


class TestAudiobook:
    """Test audiobook operations."""

    def test_add_audiobook(self, db: DatabaseManager) -> None:
        """Test adding an audiobook."""
        repo = AudiobookRepository(db)
        repo.add(title="Test Book", author="Test Author", duration=3600.0)
        books = repo.get_all()
        assert len(books) >= 1
        assert books[0]["title"] == "Test Book"

    def test_update_position(self, db: DatabaseManager) -> None:
        """Test updating audiobook position."""
        repo = AudiobookRepository(db)
        book_id = repo.add(title="Test Book", duration=3600.0)
        repo.update_position(book_id, 120.5)
        book = db.fetchone("SELECT * FROM audiobooks WHERE id = ?", (book_id,))
        assert book["last_position"] == 120.5


class TestDownload:
    """Test download operations."""

    def test_add_download(self, db: DatabaseManager) -> None:
        """Test adding a download."""
        repo = DownloadRepository(db)
        repo.add("http://test/download.mp3", "Test Download", "audio", "mp3", "320")
        queued = repo.get_queued()
        assert len(queued) >= 1

    def test_update_progress(self, db: DatabaseManager) -> None:
        """Test updating download progress."""
        repo = DownloadRepository(db)
        dl_id = repo.add("http://test/download.mp3", "Test")
        repo.update_progress(dl_id, 50.0, "downloading")
        dl = db.fetchone("SELECT * FROM downloads WHERE id = ?", (dl_id,))
        assert dl["progress"] == 50.0
        assert dl["status"] == "downloading"


class TestSchedule:
    """Test schedule operations."""

    def test_add_schedule(self, db: DatabaseManager) -> None:
        """Test adding a recording schedule."""
        repo = ScheduleRepository(db)
        repo.add("http://test/stream", "Test Recording", "radio",
                 "2026-08-05T12:00:00", duration=3600, recurrence="daily")
        schedules = repo.get_all()
        assert len(schedules) >= 1
        assert schedules[0]["title"] == "Test Recording"
