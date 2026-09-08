"""Saved speech choices must reach both previews and actual book reading."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import wx

from radiomaster.services.audiobook_tts import configured_tts
from radiomaster.ui.audiobook_panel import AudiobookPanel
from radiomaster.ui.settings_dialog import AudiobooksPanel, SettingsDialog
from radiomaster.utils.config import ConfigManager


def fake_engine():
    engine = MagicMock()
    engine.available = True
    engine.get_voices.return_value = [
        {"id": "voice-a", "name": "Voice A"},
        {"id": "voice-b", "name": "Voice B"},
    ]
    return engine


@pytest.fixture
def settings(tmp_path):
    app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None)
    config = ConfigManager(str(tmp_path))
    engine = fake_engine()
    with patch("radiomaster.services.audiobook_tts.SAPITTS", return_value=engine):
        panel = AudiobooksPanel(frame, config)
        yield panel, config, engine
        frame.Destroy()
        app.ProcessPendingEvents()


def test_audiobooks_settings_fit_dialog(settings):
    panel, config, engine = settings
    dialog = SettingsDialog(panel.GetParent(), config)
    try:
        dialog.Layout()
        dialog._switch_to(dialog.category_classes.index(AudiobooksPanel))
        dialog.Layout()
        current = dialog._current_panel
        required = current.main_sizer.GetMinSize()
        available = current.GetClientSize()
        assert required.width <= available.width
        assert required.height <= available.height
    finally:
        dialog.Destroy()


def test_settings_preview_is_not_saved_until_apply(settings):
    panel, config, engine = settings
    assert AudiobooksPanel in SettingsDialog.category_classes
    assert panel.engine_choice.GetName() == "Audiobook TTS Engine"
    assert panel.voice_choice.GetName() == "Audiobook TTS Voice"
    panel.voice_choice.SetSelection(2)
    panel.rate_spin.SetValue(3)
    panel.volume_spin.SetValue(65)
    panel._on_preview(wx.CommandEvent())
    engine.set_voice.assert_called_with("voice-b")
    engine.set_rate.assert_called_with(3)
    engine.set_volume.assert_called_with(65)
    engine.speak.assert_called_once()
    assert config.get("audiobooks.tts_voice") == ""
    panel.onDiscard()
    engine.stop.assert_called()
    assert config.get("audiobooks.tts_voice") == ""
    panel.onSave()
    config.save()
    reloaded = ConfigManager(config._config_dir)
    assert reloaded.get("audiobooks.tts_engine") == "sapi5"
    assert reloaded.get("audiobooks.tts_voice") == "voice-b"
    assert reloaded.get("audiobooks.tts_rate") == 3
    assert reloaded.get("audiobooks.tts_volume") == 65


def test_missing_saved_voice_is_preserved_until_user_changes_it(settings):
    panel, config, engine = settings
    panel._load_voices("removed-voice")
    assert "unavailable" in panel.voice_status.GetLabel().lower()
    panel.onSave()
    assert config.get("audiobooks.tts_voice") == "removed-voice"
    with pytest.raises(ValueError, match="no longer installed"):
        configured_tts(config)
    engine.speak.assert_not_called()


def test_engine_unavailable_disables_preview(settings):
    panel, config, engine = settings
    engine.available = False
    panel._load_voices("")
    assert not panel.preview_btn.IsEnabled()
    assert not panel.voice_choice.IsEnabled()
    assert "unavailable" in panel.voice_status.GetLabel().lower()


def test_book_reading_uses_saved_voice_and_stops_previous_reading(settings):
    panel, config, engine = settings
    config.set("audiobooks.tts_voice", value="voice-b")
    config.set("audiobooks.tts_rate", value=-2)
    config.set("audiobooks.tts_volume", value=80)
    previous = MagicMock()
    chapters = MagicMock()
    chapters.GetFirstSelected.return_value = 0
    chapters.GetItemData.return_value = 0
    book_panel = SimpleNamespace(
        _current_path="book", _current_book={"chapters": [{"text": "Chapter text"}]},
        _chapter_list=chapters, _tts=previous, _btn_stop_tts=MagicMock(),
    )
    with patch.object(ConfigManager, "get_instance", return_value=config):
        AudiobookPanel._on_tts(book_panel, wx.CommandEvent())
    previous.stop.assert_called_once()
    engine.set_voice.assert_called_with("voice-b")
    engine.set_rate.assert_called_with(-2)
    engine.set_volume.assert_called_with(80)
    engine.speak.assert_called_once_with("Chapter text")
    AudiobookPanel._on_stop_tts(book_panel, wx.CommandEvent())
    engine.stop.assert_called()


def test_speech_monitor_uses_ui_timer_and_stop_cancels_it():
    from radiomaster.services.sapi_tts import SAPITTS

    with patch.object(SAPITTS, "_initialize"), patch("wx.CallLater") as later:
        engine = SAPITTS()
        engine._speaker = MagicMock()
        engine._speaker.Status.RunningState = 1
        complete = MagicMock()
        engine.on_complete(complete)
        engine.speak("Sample")
        assert later.call_args.args[0] == 100
        later.call_args.args[1]()
        complete.assert_called_once()
        assert not engine.is_speaking
        engine.speak("Another sample")
        engine.stop()
        later.return_value.Stop.assert_called()
