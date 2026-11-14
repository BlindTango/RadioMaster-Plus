"""YouTube results-list context menu: downloads, whole-channel download, load more."""

from unittest.mock import MagicMock, patch

from radiomaster.ui.youtube_panel import YouTubePanel


def panel_with(videos, **attrs):
    panel = MagicMock()
    panel._channel_context = None
    panel._result_type = "video"
    panel._channel_page_size = 2
    panel._db = MagicMock()
    panel._quality_choice.GetStringSelection.return_value = "best"
    panel._audio_format_choice.GetStringSelection.return_value = "mp3"
    panel._entry_url = YouTubePanel._entry_url
    for k, v in attrs.items():
        setattr(panel, k, v)
    return panel


def test_current_channel_prefers_the_channel_being_browsed():
    panel = panel_with([], _channel_context={"url": "u", "title": "T", "id": "UC1", "key": 1})
    assert YouTubePanel._current_channel(panel) == {"url": "u", "title": "T", "id": "UC1"}


def test_current_channel_falls_back_to_selected_videos_channel():
    panel = panel_with([])
    panel._get_selected_video.return_value = {
        "channel_url": "https://youtube.com/@c", "channel": "C", "channel_id": "UC2"}
    assert YouTubePanel._current_channel(panel)["url"] == "https://youtube.com/@c"


def test_current_channel_is_none_without_channel_info():
    panel = panel_with([])
    panel._get_selected_video.return_value = {"title": "x"}
    assert YouTubePanel._current_channel(panel) is None


def test_entry_url_builds_watch_link_from_id():
    assert YouTubePanel._entry_url({"id": "abc"}) == "https://www.youtube.com/watch?v=abc"
    assert YouTubePanel._entry_url({"url": "https://y/watch?v=1"}) == "https://y/watch?v=1"


def test_queue_downloads_adds_every_video_as_video_or_audio():
    panel = panel_with([])
    manager = MagicMock()
    app = MagicMock(download_manager=manager)
    with patch("radiomaster.ui.youtube_panel.wx.GetApp", return_value=app), \
         patch("radiomaster.database.repository.DownloadRepository") as repo, \
         patch("radiomaster.utils.paths.get_downloads_dir", return_value="out"):
        repo.return_value.add.return_value = 7
        assert YouTubePanel._queue_downloads(
            panel, [{"id": "a", "title": "A"}, {"id": "b"}, {}], audio=False) == 2
        assert manager.add_download.call_count == 2
        manager.reset_mock()
        YouTubePanel._queue_downloads(panel, [{"id": "a"}], audio=True)
        assert manager.add_download.call_args.kwargs["extract_audio"] is True


def test_channel_download_pages_through_every_video():
    panel = panel_with([])
    panel._current_channel.return_value = {"url": "u", "title": "T", "id": ""}
    pages = [[{"id": "1"}, {"id": "2"}], [{"id": "3"}, {"id": "4"}], [{"id": "5"}]]
    calls = []

    class Fake:
        def get_channel_videos(self, url, size, start=1, channel_id=""):
            calls.append(start)
            return pages[len(calls) - 1]

    captured = {}
    with patch("radiomaster.services.youtube_dl.YouTubeService", Fake), \
         patch("radiomaster.ui.youtube_panel.call_after_safe",
               side_effect=lambda w, fn, *a: captured.update(args=a)), \
         patch("radiomaster.ui.youtube_panel.threading.Thread",
               side_effect=lambda target, daemon: MagicMock(start=target)):
        YouTubePanel._on_download_channel(panel, None)
    assert calls == [1, 3, 5]
    assert [v["id"] for v in captured["args"][1]] == ["1", "2", "3", "4", "5"]
