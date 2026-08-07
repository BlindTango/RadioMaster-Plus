"""Tests for services."""

import pytest
from unittest.mock import patch, MagicMock
from radiomaster.services.podcast_manager import PodcastManager
from radiomaster.services.lyrics_service import LyricsService
from radiomaster.services.radio_browser import RadioBrowserClient


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
