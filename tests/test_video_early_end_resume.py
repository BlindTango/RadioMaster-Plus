"""A video whose connection dies part-way resumes where it stopped; closing the window does not."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from radiomaster.engine.playback_engine import PlaybackEngine
from radiomaster.services.video_stream import VideoStream
from radiomaster.ui.youtube_panel import YouTubePanel


def engine_with(*, source_ended, position, duration=600.0, live=False, callback=True):
    engine = SimpleNamespace(
        _video_stream=SimpleNamespace(source_ended=source_ended),
        _on_early_end=MagicMock() if callback else None,
        _position=position, _duration=duration, _is_live=live,
        EARLY_END_MARGIN_SECONDS=PlaybackEngine.EARLY_END_MARGIN_SECONDS,
    )
    PlaybackEngine._maybe_report_early_end(engine)
    return engine


def test_source_dying_part_way_asks_to_resume_at_the_position():
    engine = engine_with(source_ended=True, position=240.0)
    engine._on_early_end.assert_called_once_with(240.0)


def test_player_closed_by_the_user_does_not_resume():
    assert not engine_with(source_ended=False, position=240.0)._on_early_end.called


def test_natural_end_does_not_resume():
    assert not engine_with(source_ended=True, position=595.0)._on_early_end.called


def test_live_or_unknown_length_does_not_resume():
    assert not engine_with(source_ended=True, position=30.0, live=True)._on_early_end.called
    assert not engine_with(source_ended=True, position=30.0, duration=0.0)._on_early_end.called


def test_no_listener_is_fine():
    engine_with(source_ended=True, position=240.0, callback=False)


def test_resume_start_is_passed_to_ffmpeg_for_both_inputs():
    command = VideoStream({"video_url": "https://m/v", "audio_url": "https://m/a"}, start_at=125.5)._command()
    assert command.count("-ss") == 2
    assert command[command.index("-ss") + 1] == "125.500"
    assert "-ss" not in VideoStream({"video_url": "v", "audio_url": "a"})._command()


def panel(**attrs):
    p = MagicMock()
    p._engine.playback_generation = 3
    p._current_source_url = "https://youtube.com/watch?v=x"
    p._current_source_title = "T"
    p._current_source_duration = 600.0
    p._early_end_resumes = 0
    p._play_request_seq = 0
    p.MAX_EARLY_END_RESUMES = YouTubePanel.MAX_EARLY_END_RESUMES
    for k, v in attrs.items():
        setattr(p, k, v)
    return p


def test_panel_resumes_slightly_before_the_drop():
    p = panel()
    with patch("radiomaster.ui.youtube_panel.threading.Thread") as thread:
        YouTubePanel._resume_after_early_end(p, 240.0, 3)
    assert p._resume_at == 238.0
    assert p._early_end_resumes == 1
    thread.return_value.start.assert_called_once()


def test_panel_ignores_a_stale_drop_after_the_user_moved_on():
    p = panel()
    with patch("radiomaster.ui.youtube_panel.threading.Thread") as thread:
        YouTubePanel._resume_after_early_end(p, 240.0, 2)
    thread.assert_not_called()


def test_panel_gives_up_after_repeated_drops_and_says_why():
    p = panel(_early_end_resumes=YouTubePanel.MAX_EARLY_END_RESUMES)
    with patch("radiomaster.ui.youtube_panel.threading.Thread") as thread:
        YouTubePanel._resume_after_early_end(p, 240.0, 3)
    thread.assert_not_called()
    assert "lower YouTube video quality" in p._set_status.call_args.args[0]
