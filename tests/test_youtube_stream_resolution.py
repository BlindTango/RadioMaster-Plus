"""Resolve playable metadata and surface the extractor's actual failure reason."""

import json
import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest

from radiomaster.services.youtube_dl import YouTubeService
from radiomaster.ui.youtube_panel import YouTubePanel


def extract(metadata, *, returncode=0, stderr=""):
    service = YouTubeService()
    stdout = metadata if isinstance(metadata, str) else json.dumps(metadata)
    with patch(
        "radiomaster.services.youtube_dl.subprocess.run",
        return_value=Mock(returncode=returncode, stdout=stdout, stderr=stderr),
    ):
        result = service.get_stream_info("https://www.youtube.com/watch?v=test")
    return service, result


def test_usable_metadata_survives_warning_lines_and_nonzero_exit():
    metadata = {"url": "https://media.test/video", "title": "Test video", "duration": 65}
    service, result = extract(
        "a warning before JSON\n" + json.dumps(metadata),
        returncode=1,
        stderr="ERROR: One optional format was unavailable",
    )
    assert result["url"] == "https://media.test/video"
    assert service.last_stream_error == ""


def test_nested_download_formats_keep_both_inputs_and_their_headers():
    _, result = extract(
        {
            "title": "Video",
            "requested_downloads": [
                {
                    "requested_formats": [
                        {
                            "url": "https://media.test/video",
                            "vcodec": "av1",
                            "acodec": "none",
                            "http_headers": {"User-Agent": "VideoAgent"},
                        },
                        {
                            "url": "https://media.test/audio",
                            "vcodec": None,
                            "acodec": "opus",
                            "http_headers": {"User-Agent": "AudioAgent"},
                        },
                    ]
                },
            ],
        }
    )
    assert result["video_inputs"]["video_url"] == "https://media.test/video"
    assert result["video_inputs"]["audio_url"] == "https://media.test/audio"
    assert result["video_inputs"]["audio_headers"] == {"User-Agent": "AudioAgent"}


def test_nested_combined_format_does_not_create_duplicate_video_audio_inputs():
    _, result = extract(
        {
            "requested_downloads": [
                None,
                {
                    "url": "https://media.test/combined",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "http_headers": {"User-Agent": "CombinedAgent"},
                },
            ]
        }
    )
    assert result["url"] == "https://media.test/combined"
    assert result["video_inputs"] is None
    assert result["http_headers"] == {"User-Agent": "CombinedAgent"}


def test_failure_reason_is_preserved_instead_of_only_a_generic_message():
    service, result = extract(
        "",
        returncode=1,
        stderr="WARNING: retrying\nERROR: This video is private. Sign in to view it.",
    )
    assert result is None
    assert service.last_stream_error == "This video is private. Sign in to view it."


def test_no_stream_in_successful_response_is_logged_and_explained(caplog):
    service, result = extract({"title": "Video", "formats": []})
    assert result is None
    assert "no playable" in service.last_stream_error
    assert "YouTube stream extraction failed" in caplog.text


def test_flat_channel_or_playlist_metadata_is_not_returned_as_a_media_stream():
    _, result = extract({"_type": "url", "url": "https://www.youtube.com/@channel"})
    assert result is None


def test_resolution_timeout_has_an_actionable_message():
    service = YouTubeService()
    with patch(
        "radiomaster.services.youtube_dl.subprocess.run",
        side_effect=subprocess.TimeoutExpired("yt-dlp", 30),
    ):
        assert service.get_stream_info("https://www.youtube.com/watch?v=test") is None
    assert "timed out" in service.last_stream_error


def test_worker_delivers_failure_details_once():
    panel = MagicMock(_play_request_seq=1)
    with (
        patch("radiomaster.services.youtube_dl.YouTubeService") as service,
        patch("radiomaster.ui.youtube_panel.wx.CallAfter") as schedule,
    ):
        service.return_value.get_stream_info.return_value = None
        service.return_value.last_stream_error = "The video is unavailable."
        YouTubePanel._resolve_and_play(panel, "https://www.youtube.com/watch?v=test", "Test", 0, 1)
    service.return_value.get_stream_info.assert_called_once()
    assert schedule.call_args.kwargs["error"] == "The video is unavailable."


def test_stale_failure_does_not_show_an_error_for_a_newer_track():
    panel = MagicMock(_play_request_seq=2, _playback_generation_at_request=None)
    with patch("radiomaster.ui.youtube_panel.wx.MessageBox") as dialog:
        YouTubePanel._apply_play_result(panel, None, "Old", seq=1, error="Old request failed")
    dialog.assert_not_called()


@pytest.mark.parametrize(
    "kind,method", [("channel", "_open_selected_channel"), ("playlist", "_open_selected_playlist")]
)
def test_transport_play_opens_collections_instead_of_resolving_them_as_videos(kind, method):
    panel = MagicMock(_result_type=kind)
    YouTubePanel._on_play(panel, None)
    getattr(panel, method).assert_called_once()
    panel._engine.stop.assert_not_called()
    panel._get_selected_video.assert_not_called()
