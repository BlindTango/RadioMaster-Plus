"""Subscribed channels must open the right videos and keep older uploads reachable."""

import gc
import json
import subprocess
import threading
import time
from unittest.mock import Mock, patch

import pytest
import wx

from radiomaster.database.connection import DatabaseManager
from radiomaster.database.repository import YouTubeChannelRepository
from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.services.youtube_dl import YouTubeChannelError, YouTubeService
from radiomaster.ui.youtube_panel import YouTubePanel
from radiomaster.utils.config import ConfigManager

CHANNEL_ID = "UC" + "a" * 22


@pytest.fixture
def panel(tmp_path, monkeypatch):
    gc.collect()
    app = wx.App(False)
    wx.Log.SetActiveTarget(wx.LogStderr())
    monkeypatch.setattr(ConfigManager, "_instance", ConfigManager._instance)
    ConfigManager(str(tmp_path / "config"))
    db = DatabaseManager(str(tmp_path / "database"))
    db.initialize()
    repository = YouTubeChannelRepository(db)
    repository.add(CHANNEL_ID, "Channel A", "https://www.youtube.com/@channelA")
    repository.add("UC" + "b" * 22, "Channel B", "https://www.youtube.com/@channelB")
    frame = wx.Frame(None)
    widget = YouTubePanel(frame, db, PlaybackEngine())
    widget._set_status = Mock()
    frame.Show()
    wx.Yield()
    yield widget
    frame.Destroy()
    wx.Yield()
    db.close()
    assert app


def pump_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        wx.Yield()
        time.sleep(0.005)
    assert predicate()


def video(index):
    return {
        "id": f"video{index}",
        "title": f"Video {index}",
        "url": f"https://www.youtube.com/watch?v=video{index}",
        "duration": 65.5,
    }


def event_for(index):
    event = wx.ListEvent(wx.EVT_LIST_ITEM_ACTIVATED.typeId)
    event.SetIndex(index)
    return event


def test_activation_uses_event_row_when_another_channel_is_selected(panel):
    with patch.object(YouTubeService, "get_channel_videos", return_value=[video(1)]) as fetch:
        panel._channels_list.Select(0)
        panel._on_channel_activated(event_for(1))
        pump_until(lambda: not panel._channel_loading)
    assert any(call.args[0] == "https://www.youtube.com/@channelB" for call in fetch.call_args_list)
    assert panel._channels_list.GetFirstSelected() == 1
    assert panel._results_list.GetItemText(0) == "Video 1"
    assert panel._get_selected_video()["id"] == "video1"
    assert panel.FindFocus() is panel._results_list


def test_selecting_subscription_populates_videos_without_playing_channel(panel):
    with (
        patch.object(YouTubeService, "get_channel_videos", return_value=[video(1)]) as fetch,
        patch.object(panel._engine, "play") as play,
    ):
        panel._channels_list.Select(0)
        pump_until(lambda: panel._results_list.GetItemCount() == 1)
    assert fetch.call_args.kwargs["channel_id"] == CHANNEL_ID
    assert panel._results_list.GetItemText(0, 1) == "1:05"
    assert panel._btn_view_videos.IsEnabled()
    play.assert_not_called()


def test_view_button_and_paging_reach_more_than_thirty_videos(panel):
    first = [video(index) for index in range(100)]
    second = [video(99), video(100), video(101)]
    with patch.object(YouTubeService, "get_channel_videos", side_effect=[first, second]) as fetch:
        panel._on_channel_activated(event_for(0))
        pump_until(lambda: not panel._channel_loading)
        assert panel._results_list.GetItemCount() == 100
        assert panel._btn_more_videos.IsEnabled()
        panel._on_more_videos(None)
        pump_until(lambda: not panel._channel_loading)
    assert [call.kwargs["start"] for call in fetch.call_args_list] == [1, 101]
    assert panel._results_list.GetItemCount() == 102
    assert len({entry["id"] for entry in panel._search_results}) == 102
    assert not panel._btn_more_videos.IsEnabled()
    assert panel._get_selected_video()["id"] == "video100"


def test_enter_after_automatic_load_selects_first_video_without_loading_twice(panel):
    with patch.object(YouTubeService, "get_channel_videos", return_value=[video(1)]) as fetch:
        panel._channels_list.Select(0)
        pump_until(lambda: panel._results_list.GetItemCount() == 1)
        panel._on_channel_activated(event_for(0))
    fetch.assert_called_once()
    assert panel._get_selected_video()["id"] == "video1"
    assert panel.FindFocus() is panel._results_list


def test_loading_more_can_retry_after_error_without_losing_existing_videos(panel):
    first = [video(index) for index in range(100)]
    with patch.object(
        YouTubeService,
        "get_channel_videos",
        side_effect=[first, YouTubeChannelError("Temporary outage"), [video(100)]],
    ) as fetch:
        panel._on_channel_activated(event_for(0))
        pump_until(lambda: not panel._channel_loading)
        panel._on_more_videos(None)
        pump_until(lambda: not panel._channel_loading)
        assert panel._results_list.GetItemCount() == 100
        assert panel._btn_more_videos.IsEnabled()
        panel._on_more_videos(None)
        pump_until(lambda: not panel._channel_loading)
    assert [call.kwargs["start"] for call in fetch.call_args_list] == [1, 101, 101]
    assert panel._results_list.GetItemCount() == 101


def test_partial_extraction_keeps_rows_and_retries_same_page_instead_of_reporting_end(panel):
    partial = [dict(video(index), playlist_index=index) for index in range(1, 51)]
    full = [dict(video(index), playlist_index=index) for index in range(1, 101)]
    responses = [
        Mock(
            returncode=1,
            stdout="\n".join(json.dumps(row) for row in partial),
            stderr="Connection reset while reading continuation",
        ),
        Mock(returncode=0, stdout="\n".join(json.dumps(row) for row in full), stderr=""),
    ]
    with patch("radiomaster.services.youtube_dl.subprocess.run", side_effect=responses) as run:
        panel._on_channel_activated(event_for(0))
        pump_until(lambda: not panel._channel_loading)
        assert panel._results_list.GetItemCount() == 50
        assert panel._btn_more_videos.IsEnabled()
        assert "interrupted" in panel._set_status.call_args.args[0]
        assert "End of channel" not in panel._set_status.call_args.args[0]
        panel._on_more_videos(None)
        pump_until(lambda: not panel._channel_loading)
    commands = [call.args[0] for call in run.call_args_list]
    assert [command[command.index("--playlist-items") + 1] for command in commands] == [
        "1:100",
        "1:100",
    ]
    assert panel._results_list.GetItemCount() == 100
    assert panel._channel_context["next_start"] == 101
    assert panel._btn_more_videos.IsEnabled()


def test_failed_channel_load_is_reported_and_view_button_retries(panel):
    with patch.object(
        YouTubeService,
        "get_channel_videos",
        side_effect=[YouTubeChannelError("Temporary outage"), [video(1)]],
    ):
        panel._channels_list.Select(0)
        pump_until(lambda: "Temporary outage" in str(panel._set_status.call_args))
        assert "Temporary outage" in panel._set_status.call_args.args[0]
        panel._on_view_videos(None)
        pump_until(lambda: not panel._channel_loading)
    assert panel._results_list.GetItemCount() == 1


def test_old_channel_result_cannot_replace_newer_selection(panel):
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    def fetch(url, *args, **kwargs):
        if url.endswith("channelA"):
            started.set()
            release.wait(3)
            finished.set()
            return [video(1)]
        return [video(2)]

    try:
        with patch.object(YouTubeService, "get_channel_videos", side_effect=fetch):
            panel._on_channel_activated(event_for(0))
            assert started.wait(1)
            panel._on_channel_activated(event_for(1))
            pump_until(lambda: not panel._channel_loading)
            assert panel._results_list.GetItemText(0) == "Video 2"
    finally:
        release.set()
        assert finished.wait(2)
        wx.Yield()
    assert panel._results_list.GetItemText(0) == "Video 2"


def test_search_invalidates_pending_channel_results(panel):
    panel._channel_context = {"title": "Old channel"}
    old_request = panel._browse_request_seq
    panel._begin_browse()
    panel._apply_search_results([video(2)], "New search", request_seq=panel._browse_request_seq)
    panel._apply_channel_page(old_request, 1, [video(1)])
    assert panel._results_list.GetItemText(0) == "Video 2"


def test_skipped_unavailable_uploads_do_not_hide_following_pages(panel):
    entries = [dict(video(99), playlist_index=100)]
    with patch.object(YouTubeService, "get_channel_videos", return_value=entries):
        panel._on_channel_activated(event_for(0))
        pump_until(lambda: not panel._channel_loading)
    assert panel._btn_more_videos.IsEnabled()


def test_fast_arrow_selection_only_fetches_last_channel(panel):
    with patch.object(YouTubeService, "get_channel_videos", return_value=[video(2)]) as fetch:
        panel._channels_list.Select(0)
        panel._channels_list.Select(0, False)
        panel._channels_list.Select(1)
        pump_until(lambda: panel._results_list.GetItemCount() == 1)
    fetch.assert_called_once()
    assert fetch.call_args.args[0].endswith("channelB")


def test_channel_service_uses_uploads_playlist_and_inclusive_page_range():
    result = Mock(returncode=0, stdout=json.dumps(video(101)), stderr="")
    with (
        patch("radiomaster.services.youtube_dl.subprocess.run", return_value=result) as run,
        patch("radiomaster.services.youtube_dl._extraction_args", return_value=[]),
    ):
        entries = YouTubeService().get_channel_videos(
            "https://www.youtube.com/@channel", 100, start=101, channel_id=CHANNEL_ID
        )
    command = run.call_args.args[0]
    assert "https://www.youtube.com/playlist?list=UU" + "a" * 22 in command
    assert command[command.index("--playlist-items") + 1] == "101:200"
    assert "--skip-download" in command
    assert entries[0]["id"] == "video101"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@channel/videos?view=0",
        "https://www.youtube.com/@channel/shorts#top",
    ],
)
def test_channel_url_normalization_does_not_append_videos_after_query_or_tab(url):
    with patch(
        "radiomaster.services.youtube_dl.subprocess.run",
        return_value=Mock(returncode=0, stdout="", stderr=""),
    ) as run:
        YouTubeService().get_channel_videos(url)
    assert "https://www.youtube.com/@channel/videos" in run.call_args.args[0]


def test_channel_errors_are_distinct_from_empty_results_and_partial_results_survive():
    service = YouTubeService()
    with (
        patch(
            "radiomaster.services.youtube_dl.subprocess.run",
            return_value=Mock(returncode=1, stdout="", stderr="Channel unavailable"),
        ),
        pytest.raises(YouTubeChannelError, match="Channel unavailable"),
    ):
        service.get_channel_videos("https://www.youtube.com/@channel")
    with patch(
        "radiomaster.services.youtube_dl.subprocess.run",
        return_value=Mock(returncode=1, stdout=json.dumps(video(1)) + "\nnull\nbad", stderr=""),
    ):
        assert service.get_channel_videos("https://www.youtube.com/@channel") == [video(1)]
    with (
        patch(
            "radiomaster.services.youtube_dl.subprocess.run",
            side_effect=subprocess.TimeoutExpired("yt-dlp", 60),
        ),
        pytest.raises(YouTubeChannelError, match="timed out"),
    ):
        service.get_channel_videos("https://www.youtube.com/@channel")
