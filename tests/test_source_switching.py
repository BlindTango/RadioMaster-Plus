"""Source replacement and fast YouTube playback regressions."""

import os
import json
import sys
import time
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
import wx

from radiomaster.engine.bass_radio_engine import BassRadioEngine
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.services.youtube_dl import YouTubeService, _extraction_args
from radiomaster.services.video_stream import VideoStream
from radiomaster.ui.podcast_panel import PodcastPanel
from radiomaster.ui.radio_panel import RadioPanel
from radiomaster.ui.youtube_panel import YouTubePanel


@pytest.mark.parametrize("video", [False, True])
def test_new_source_interrupts_unresponsive_radio_without_manual_stop(video):
    script = (
        "import json, sys, time; "
        "print(json.dumps({'ok': True, 'ready': True}), flush=True); "
        "sys.stdin.readline(); time.sleep(60)"
    )
    old = BassRadioEngine([sys.executable, "-u", "-c", script], os.environ.copy())
    old._state = "playing"
    player = PlaybackEngine()
    player._bass_radio = old
    player._using_bass_radio = True
    player._is_live = True
    player._current_url = "https://radio/stream"
    fresh = MagicMock(available=True)
    started = time.monotonic()
    try:
        with patch.object(BassRadioEngine, "create_if_available", return_value=fresh), \
             patch.object(player, "_start_process") as start_video:
            player.play("episode.mp3", title="New item", duration=100, is_video=video)
        assert time.monotonic() - started < 3
        assert not old.available
        assert player.current_url == "episode.mp3"
        if video:
            start_video.assert_called_once_with("episode.mp3", True)
        else:
            fresh.play.assert_called_once_with("episode.mp3", "New item", "", 100,
                                               seekable=True)
    finally:
        old.close()


def test_podcast_enter_uses_activated_episode_when_selection_is_missing():
    panel = MagicMock()
    panel._episode_data = [{"audio_url": "episode.mp3"}]
    panel._episode_list.GetFirstSelected.return_value = -1
    event = wx.ListEvent(wx.EVT_LIST_ITEM_ACTIVATED.typeId)
    event.SetIndex(0)
    PodcastPanel._on_play(panel, event)
    panel._play_episode_at.assert_called_once_with(0, offer_resume=True)


def test_previous_station_metadata_does_not_replace_podcast_title():
    panel = MagicMock()
    panel._now_playing_generation = 1
    panel.engine.current_url = "episode.mp3"
    panel.engine._is_live = False
    RadioPanel._publish_radio_song(panel, "https://radio/stream", 1, "Artist - Song")
    panel.now_playing.set_now_playing.assert_not_called()
    panel.on_now_playing_changed.assert_not_called()


def test_youtube_resolution_starts_stream_without_full_download():
    panel = MagicMock()
    panel._play_request_seq = 1
    stream = {"url": "https://media/stream", "title": "Video", "duration": 30,
              "http_headers": {"User-Agent": "Player"}}
    with patch("radiomaster.services.youtube_dl.YouTubeService") as service, \
         patch("radiomaster.ui.youtube_panel.wx.CallAfter") as schedule:
        service.return_value.get_stream_info.return_value = stream
        YouTubePanel._resolve_and_play(panel, "https://youtube/watch?v=test", "Test", 0, 1)
    service.return_value.download_to_temp.assert_not_called()
    schedule.assert_called_once_with(panel._apply_play_result, stream["url"], "Video", 30,
                                     1, stream["http_headers"], video_info=stream)


def test_delayed_youtube_result_cannot_replace_newer_podcast():
    panel = MagicMock()
    player = PlaybackEngine()
    panel._engine = player
    panel._play_request_seq = 1
    panel._playback_generation_at_request = player.playback_generation
    player.stop(wait=False)
    with patch.object(player, "play") as play:
        YouTubePanel._apply_play_result(panel, "https://media/old", "Old video", seq=1)
    play.assert_not_called()
    panel._publish_video_info.assert_not_called()


def test_bundled_deno_and_ffmpeg_are_passed_to_extractor(tmp_path):
    (tmp_path / "deno.exe").touch()
    with patch("radiomaster.services.youtube_dl.get_tools_dir", return_value=str(tmp_path)), \
         patch("radiomaster.services.youtube_dl.get_yt_dlp_proxy_args", return_value=[]):
        args = _extraction_args()
    assert args == ["--ffmpeg-location", str(tmp_path), "--js-runtimes",
                    f"deno:{tmp_path / 'deno.exe'}"]


def test_service_creation_does_not_launch_an_extra_version_check():
    with patch("radiomaster.services.youtube_dl.subprocess.run") as run:
        YouTubeService()
    run.assert_not_called()


def test_podcast_progress_is_not_updated_from_radio_position():
    panel = MagicMock()
    panel._current_episode_id = 1
    panel._last_played_url = "episode.mp3"
    panel._engine.current_url = "https://radio/stream"
    panel._engine.state = "playing"
    with patch("radiomaster.database.repository.EpisodeRepository") as repo:
        PodcastPanel._save_position(panel)
    repo.assert_not_called()


def test_separate_youtube_tracks_are_preserved_for_streaming():
    response = MagicMock(returncode=0, stdout=json.dumps({
        "title": "Video", "requested_formats": [
            {"url": "https://media/video", "vcodec": "av1", "acodec": "none",
             "http_headers": {"User-Agent": "VideoPlayer"}},
            {"url": "https://media/audio", "vcodec": "none", "acodec": "opus",
             "http_headers": {"User-Agent": "AudioPlayer"}},
        ],
    }))
    with patch("radiomaster.services.youtube_dl.subprocess.run", return_value=response):
        result = YouTubeService().get_stream_info("https://youtube/watch?v=test")
    assert result["url"] == "https://media/video"
    assert result["video_inputs"] == {
        "video_url": "https://media/video", "audio_url": "https://media/audio",
        "video_headers": {"User-Agent": "VideoPlayer"},
        "audio_headers": {"User-Agent": "AudioPlayer"},
    }


def test_stopping_video_stream_interrupts_a_blocked_muxer():
    stream = VideoStream({})
    script = (
        "import sys,time; sys.stdout.buffer.write(b'x'*1024); "
        "sys.stdout.buffer.flush(); time.sleep(60)"
    )
    response = None
    try:
        with patch.object(stream, "_command", return_value=[sys.executable, "-u", "-c", script]):
            url = stream.start()
            response = urllib.request.urlopen(url, timeout=3)
            assert response.read(1024) == b"x" * 1024
            process = stream._process
            started = time.monotonic()
            stream.close()
            process.wait(timeout=2)
            assert time.monotonic() - started < 3
            stream.close()
    finally:
        if response is not None:
            response.close()
        stream.close()
