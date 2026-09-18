"""Completed local downloads must be reusable without a working downloader."""

from unittest.mock import MagicMock

import pytest

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import DownloadRepository, PodcastRepository
from radiomaster.services.download_manager import DownloadManager


@pytest.fixture
def downloads(tmp_path):
    db = DatabaseManager(str(tmp_path / "db"))
    db.initialize()
    yield db, DownloadRepository(db)
    db.close()


@pytest.mark.parametrize("source,audio,format", [
    ("podcast", True, "mp3"), ("", True, "flac"), ("", False, "1080p"),
])
def test_reuse_completes_history_offline(downloads, tmp_path, monkeypatch, source, audio, format):
    db, repo = downloads
    file = tmp_path / "original.media"
    file.write_bytes(b"completed media")
    options = dict(source_type=source, extract_audio=audio, format=format, quality="192k")
    original = repo.add("https://example.test/media", title="Old title", **options)
    repo.mark_completed(original, str(file))
    requested = repo.add("https://example.test/media", title="New title",
                         output_dir=str(tmp_path / "new destination"), **options)
    # Exercise the same path used by Retry / Retry all failed downloads.
    repo.update_progress(requested, 0, status="failed")
    repo.reset_for_retry(requested)
    if source == "podcast":
        podcast_id = PodcastRepository(db).add("https://example.test/feed")
        db.execute(
            "INSERT INTO episodes (podcast_id, title, audio_url, download_status) "
            "VALUES (?, 'Episode', 'https://example.test/media', 'queued')", (podcast_id,),
        )
        db.commit()
    manager = DownloadManager()
    manager.set_existing_file_lookup(repo.find_existing_file)
    manager.on_complete(repo.mark_completed)
    launch = MagicMock(side_effect=AssertionError("Downloader must not start"))
    monkeypatch.setattr("radiomaster.services.download_manager.subprocess.Popen", launch)
    manager.add_download(requested, "https://example.test/media",
                         output_dir=str(tmp_path / "new destination"),
                         format=format, extract_audio=audio)
    manager._execute_download(manager._queue.get_nowait())
    launch.assert_not_called()
    row = repo.get(requested)
    assert (row["status"], row["progress"]) == ("completed", 100)
    assert row["file_path"] == repo.get(original)["file_path"]
    assert requested not in [row["id"] for row in repo.get_queued()]
    assert not (tmp_path / "new destination").exists()
    assert file.read_bytes() == b"completed media"
    if source == "podcast":
        episode = db.fetchone("SELECT * FROM episodes WHERE podcast_id = ?", (podcast_id,))
        assert episode["download_status"] == "completed"
        assert episode["file_path"] == row["file_path"]


@pytest.mark.parametrize("difference", ["url", "format", "quality", "extract_audio",
                                         "missing", "empty", "partial", "failed", "recording"])
def test_invalid_or_different_copy_is_not_reused(downloads, tmp_path, difference):
    db, repo = downloads
    file = tmp_path / ("media.part" if difference == "partial" else "media.mp3")
    if difference != "missing":
        file.write_bytes(b"" if difference == "empty" else b"media")
    original = repo.add("https://example.test/media", format="mp3", quality="192k",
                        extract_audio=True,
                        source_type="radio_recording" if difference == "recording" else "podcast")
    repo.mark_completed(original, str(file))
    if difference == "failed":
        repo.update_progress(original, 0, status="failed")
    options = dict(url="https://example.test/media", format="mp3", quality="192k",
                   extract_audio=True, source_type="podcast")
    if difference in ("url", "format", "quality"):
        options[difference] = "different"
    elif difference == "extract_audio":
        options["extract_audio"] = False
    requested = repo.add(**options)
    assert repo.find_existing_file(requested) == ""


def test_missing_latest_copy_falls_back_to_older_completed_file(downloads, tmp_path):
    db, repo = downloads
    file = tmp_path / "existing.mp3"
    file.write_bytes(b"media")
    for path in (file, tmp_path / "deleted.mp3"):
        original = repo.add("https://example.test/media", format="mp3")
        repo.mark_completed(original, str(path))
    requested = repo.add("https://example.test/media", format="MP3")
    assert repo.find_existing_file(requested) == str(file)


def test_no_completed_copy_runs_downloader(downloads, tmp_path, monkeypatch):
    db, repo = downloads
    requested = repo.add("https://example.test/new", format="mp3")
    manager = DownloadManager()
    manager.set_existing_file_lookup(repo.find_existing_file)
    manager.on_complete(repo.mark_completed)
    process = MagicMock(returncode=0, stdout=[])
    launch = MagicMock(return_value=process)
    monkeypatch.setattr("radiomaster.services.download_manager.subprocess.Popen", launch)
    manager._execute_download(dict(id=requested, url="https://example.test/new",
                                   output_dir=str(tmp_path / "output"), format="mp3",
                                   extract_audio=True))
    launch.assert_called_once()
