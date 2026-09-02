"""Tests for services."""

import os
from unittest.mock import MagicMock, patch

import pytest

from radiomaster.services.lyrics_service import LyricsService
from radiomaster.services.podcast_manager import PodcastManager
from radiomaster.services.radio_browser import RadioBrowserClient
from radiomaster.services.update_checker import UpdateChecker, UpdateCheckError


class TestPodcastManager:
    """Test podcast feed parsing."""

    def test_parse_duration_hms(self) -> None:
        assert PodcastManager._parse_duration("01:30:45") == 5445

    def test_parse_duration_ms(self) -> None:
        assert PodcastManager._parse_duration("05:30") == 330

    def test_parse_duration_seconds(self) -> None:
        assert PodcastManager._parse_duration("120") == 120

    def test_parse_duration_empty(self) -> None:
        assert PodcastManager._parse_duration("") == 0

    def test_clean_html(self) -> None:
        html = "<p>Hello <b>World</b></p>"
        assert PodcastManager._clean_html(html) == "Hello World"

    def test_export_opml(self) -> None:
        subs = [{"title": "Test", "feed_url": "http://test/feed.xml", "website_url": "http://test.com"}]
        opml = PodcastManager.export_opml(subs)
        assert "opml" in opml
        assert "http://test/feed.xml" in opml


class TestDownloadManagerSettings:
    def test_legacy_and_invalid_audio_formats_are_normalized(self) -> None:
        from radiomaster.services.download_manager import normalize_audio_format

        assert normalize_audio_format("OGG") == "opus"
        assert normalize_audio_format("not-a-format") == "mp3"

    def test_concurrency_can_be_increased_live(self) -> None:
        from radiomaster.services.download_manager import DownloadManager

        manager = DownloadManager(2)
        fake_threads = []

        def make_thread(*args, **kwargs):
            thread = MagicMock()
            fake_threads.append(thread)
            return thread

        with patch(
            "radiomaster.services.download_manager.threading.Thread",
            side_effect=make_thread,
        ):
            manager.start()
            manager.set_max_concurrent(4)

        assert len(fake_threads) == 4
        assert all(thread.start.call_count == 1 for thread in fake_threads)
        assert manager._max_concurrent == 4

    def test_concurrency_setting_is_clamped(self) -> None:
        from radiomaster.services.download_manager import DownloadManager

        manager = DownloadManager(3)
        with patch("radiomaster.services.download_manager.threading.Thread"):
            manager.set_max_concurrent(0)
            assert manager._max_concurrent == 1
            manager.set_max_concurrent(99)
            assert manager._max_concurrent == 10


class TestRecordingSettings:
    def test_legacy_best_quality_and_invalid_format_are_normalized(self) -> None:
        from radiomaster.services.recording_session import (
            normalize_recording_format,
            normalize_recording_quality,
        )

        assert normalize_recording_quality("Best") == "best"
        assert normalize_recording_quality("invalid") == "320k"
        assert normalize_recording_format("invalid") == "mp3"
        assert normalize_recording_format("opus") == "opus"

    def test_best_recording_quality_uses_station_bitrate(self, tmp_path) -> None:
        from radiomaster.services.recording_session import RecordingSession

        session = RecordingSession(
            "https://radio.test/stream", "Test Station", str(tmp_path),
            quality="best", match_source=False,
            source_format={"codec": "aac", "bit_rate": 192000},
        )
        command = session._recording_ffmpeg_args(str(tmp_path / "recording.mp3"), None)
        assert command[command.index("-b:a") + 1] == "192000"

    def test_split_encoder_embeds_track_metadata(self, tmp_path) -> None:
        from radiomaster.services.recording_session import RecordingSession

        session = RecordingSession(
            "https://radio.test/stream", "Test Station", str(tmp_path),
            split_tracks=True, add_metadata=True,
        )
        session._last_song = "Test Artist - Test Track"
        with patch("radiomaster.services.recording_session.subprocess.Popen") as popen:
            session._start_encode_segment(str(tmp_path / "track.mp3"))

        command = popen.call_args.args[0]
        assert "title=Test Track" in command
        assert "artist=Test Artist" in command

    def test_scheduler_recording_folder_updates_live(self) -> None:
        from radiomaster.services.scheduler_service import SchedulerService

        scheduler = SchedulerService("old")
        scheduler.set_recordings_dir("new")
        assert scheduler._recordings_dir == "new"

    def test_short_metadata_segment_is_discarded_as_likely_ad(self, tmp_path) -> None:
        import time
        from pathlib import Path

        from radiomaster.services.recording_session import RecordingSession

        finalized = MagicMock()
        session = RecordingSession(
            "https://radio.test/stream", "Test Station", str(tmp_path),
            split_tracks=True, skip_short_ads=True, ad_max_duration=30,
            on_segment_finalized=finalized,
        )
        Path(session.temp_path).write_bytes(b"short segment")
        session._segment_started_at = time.monotonic() - 10
        session._finalize_encode_segment(check_for_short_ad=True)

        assert not Path(session.temp_path).exists()
        finalized.assert_not_called()

    def test_short_segment_is_kept_when_override_is_off(self, tmp_path) -> None:
        import time
        from pathlib import Path

        from radiomaster.services.recording_session import RecordingSession

        finalized = MagicMock()
        session = RecordingSession(
            "https://radio.test/stream", "Test Station", str(tmp_path),
            split_tracks=True, skip_short_ads=False, ad_max_duration=30,
            on_segment_finalized=finalized,
        )
        Path(session.temp_path).write_bytes(b"short segment")
        session._segment_started_at = time.monotonic() - 10
        session._finalize_encode_segment(check_for_short_ad=True)

        finalized.assert_called_once()


class TestYouTubePlaybackQuality:
    """YouTube playback must select separate adaptive streams; the best
    combined stream is commonly limited to low resolution and bitrate."""

    def test_temp_playback_downloads_and_merges_best_video_and_audio(self, tmp_path) -> None:
        from radiomaster.services.youtube_dl import YouTubeService

        completed = MagicMock()

        def fake_run(cmd, **kwargs):
            output_path = cmd[cmd.index("-o") + 1]
            with open(output_path, "wb") as output:
                output.write(b"merged media")
            return completed

        with patch.object(YouTubeService, "_check_available"), \
             patch("tempfile.mkstemp") as mkstemp, \
             patch("radiomaster.services.youtube_dl.subprocess.run", side_effect=fake_run) as run:
            target = tmp_path / "playback.mp4"
            fd = os.open(target, os.O_CREAT | os.O_RDWR)
            mkstemp.return_value = (fd, str(target))

            result = YouTubeService().download_to_temp("https://youtube.test/watch?v=1")

        assert result == str(target)
        command = run.call_args.args[0]
        assert command[command.index("-f") + 1] == "bestvideo+bestaudio/best"
        assert command[command.index("--concurrent-fragments") + 1] == "4"
        assert "--merge-output-format" in command

class TestLyricsService:
    """Test lyrics service."""

    def test_parse_lrc(self) -> None:
        lrc = "[00:01.50]Line 1\n[00:05.00]Line 2\n"
        result = LyricsService.parse_lrc(lrc)
        assert len(result) == 2
        assert result[0]["time"] == 1.5
        assert result[0]["text"] == "Line 1"
        assert result[1]["time"] == 5.0
        assert result[1]["text"] == "Line 2"

    def test_parse_lrc_empty(self) -> None:
        assert LyricsService.parse_lrc("") == []


class TestParseIcySong:
    """Radio's ICY StreamTitle metadata is the only source of a real song
    artist/title for lyrics lookups -- engine._current_title otherwise
    only ever held the station's own name, and no caller anywhere in the
    app ever passed a real artist, which is why lyrics never showed up."""

    def test_splits_artist_and_title(self) -> None:
        from radiomaster.ui.radio_panel import _parse_icy_song
        assert _parse_icy_song("Groove Armada - Superstylin") == ("Groove Armada", "Superstylin")

    def test_no_separator_falls_back_to_title_only(self) -> None:
        from radiomaster.ui.radio_panel import _parse_icy_song
        assert _parse_icy_song("Just A Title") == ("", "Just A Title")

    def test_splits_only_on_first_separator(self) -> None:
        from radiomaster.ui.radio_panel import _parse_icy_song
        artist, title = _parse_icy_song("DJ Shadow - Building Steam - Extended Mix")
        assert artist == "DJ Shadow"
        assert title == "Building Steam - Extended Mix"

    def test_empty_string(self) -> None:
        from radiomaster.ui.radio_panel import _parse_icy_song
        assert _parse_icy_song("") == ("", "")


class TestRadioBrowser:
    """Test radio browser client."""

    def test_server_url(self) -> None:
        # RadioBrowserClient tries a list of mirrors (falling back through
        # them in _get()) rather than resolving a single server up front.
        client = RadioBrowserClient()
        assert client._base_urls
        for server in client._base_urls:
            assert server.startswith("https://")
            assert "radio-browser.info" in server


class TestUpdateChecker:
    """GitHub's unauthenticated API rate-limits to 60 req/hour per source
    IP -- easy to hit, especially behind a shared NAT/office connection.
    A raw 403 requests exception used to be shown to the user verbatim
    ("Could not check for updates: 403 Client Error: rate limit exceeded
    for url: ..."); check() now recognizes that specific case and raises
    a clear, actionable message instead."""

    def test_rate_limit_with_reset_header(self) -> None:
        resp = MagicMock()
        resp.status_code = 403
        resp.headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"}
        with patch("radiomaster.services.update_checker.requests.get", return_value=resp):
            checker = UpdateChecker()
            with pytest.raises(UpdateCheckError) as exc_info:
                checker.check("1.0.0")
        message = str(exc_info.value)
        assert "rate limit exceeded" not in message.lower()
        assert "limit has been reached" in message.lower()

    def test_rate_limit_without_reset_header(self) -> None:
        resp = MagicMock()
        resp.status_code = 403
        resp.headers = {"X-RateLimit-Remaining": "0"}
        with patch("radiomaster.services.update_checker.requests.get", return_value=resp):
            checker = UpdateChecker()
            with pytest.raises(UpdateCheckError) as exc_info:
                checker.check("1.0.0")
        assert "resets hourly" in str(exc_info.value).lower()

    def test_403_without_rate_limit_header_falls_through(self) -> None:
        # A plain 403 (e.g. a genuinely private/missing repo) isn't a rate
        # limit -- should fall through to raise_for_status()'s normal error,
        # not the rate-limit-specific message.
        import requests as requests_module
        resp = MagicMock()
        resp.status_code = 403
        resp.headers = {}
        resp.raise_for_status.side_effect = requests_module.HTTPError("403 Forbidden")
        with patch("radiomaster.services.update_checker.requests.get", return_value=resp):
            checker = UpdateChecker()
            with pytest.raises(UpdateCheckError) as exc_info:
                checker.check("1.0.0")
        assert "limit has been reached" not in str(exc_info.value).lower()


class TestMediaPlayerReadTags:
    """The playlist's Artist column was always left blank and engine.play()
    never got an artist for local files -- harmless for playback, but it
    meant lyrics lookups for local files had no artist to search with."""

    def test_reads_title_and_artist(self) -> None:
        from radiomaster.ui.media_player_panel import MediaPlayerPanel
        fake_audio = {"title": ["Test Song"], "artist": ["Test Artist"]}
        with patch("mutagen.File", return_value=fake_audio):
            assert MediaPlayerPanel._read_tags("fake.mp3") == ("Test Song", "Test Artist")

    def test_no_tags_returns_empty(self) -> None:
        from radiomaster.ui.media_player_panel import MediaPlayerPanel
        with patch("mutagen.File", return_value=None):
            assert MediaPlayerPanel._read_tags("fake.mp3") == ("", "")

    def test_unreadable_file_does_not_raise(self) -> None:
        from radiomaster.ui.media_player_panel import MediaPlayerPanel
        with patch("mutagen.File", side_effect=Exception("boom")):
            assert MediaPlayerPanel._read_tags("fake.mp3") == ("", "")
