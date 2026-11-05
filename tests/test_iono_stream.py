"""Custom iono.fm player links must reach the audio, not an HTML decoder."""

import json
from unittest.mock import Mock, patch

import pytest

from radiomaster.engine.bass_host import BassHost, _iono_playlist_url, _resolve_playlist_url


def test_unisa_player_resolves_best_audio_and_removes_player_placeholders():
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.headers = {"content-type": "application/json"}
    response.read.return_value = json.dumps({"audio": [
        {"url": "https://edge.iono.fm/xice/207_medium.mp3", "mime": "audio/mp3", "bitrate": 80000},
        {"url": "https://edge.iono.fm/xice/207_high.aac?ref=<referer>&adToken=<adToken>&key=real",
         "mime": "audio/aac", "bitrate": 160000},
        {"url": "https://edge.iono.fm/xhls/207_high.m3u8",
         "mime": "application/x-mpegURL", "bitrate": 160000},
    ]}).encode()
    with patch("radiomaster.engine.bass_host.urllib.request.urlopen",
               return_value=response) as open_url:
        assert _resolve_playlist_url("https://iono.fm/s/207") == (
            "https://edge.iono.fm/xice/207_high.aac?key=real")
    assert open_url.call_args.args[0].full_url == "https://iframe.iono.fm/playlists/s/207"


@pytest.mark.parametrize("url", ["https://other.example/s/207", "https://iono.fm.evil.test/s/207",
                                    "https://iono.fm/e/207", "https://iono.fm/s/not-a-number"])
def test_other_urls_are_not_rewritten(url):
    assert _iono_playlist_url(url) is None


def test_player_resolution_network_failure_preserves_original_url():
    with patch("radiomaster.engine.bass_host.urllib.request.urlopen", side_effect=OSError):
        assert _resolve_playlist_url("https://iono.fm/s/207") == "https://iono.fm/s/207"


def test_known_player_is_resolved_before_native_stream_open():
    host = BassHost("unused")
    host._dll = Mock()
    with patch("radiomaster.engine.bass_host._resolve_playlist_url",
               return_value="https://edge.iono.fm/xice/207_high.aac"), \
            patch.object(host, "_try_create_url", return_value=123) as create, \
            patch.object(host, "_restart_meta_thread"):
        assert host.play("https://iono.fm/s/207", seq=1)[0]
    create.assert_called_once_with("https://edge.iono.fm/xice/207_high.aac", seekable=False)
