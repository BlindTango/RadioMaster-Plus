"""Settings > Playback > YouTube video quality."""

import pytest
import wx

from radiomaster.ui.settings_dialog import PlaybackPanel
from radiomaster.utils.config import ConfigManager


@pytest.fixture
def panel(tmp_path):
    app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None)
    config = ConfigManager(str(tmp_path))
    yield lambda: PlaybackPanel(frame, config), config
    frame.Destroy()
    app.ProcessPendingEvents()


def test_default_is_1080p_and_choices_are_named(panel):
    make, config = panel
    p = make()
    combo = p.youtube_quality_combo
    assert combo.GetName() == "YouTube video quality"
    assert [combo.GetString(i) for i in range(combo.GetCount())] == [
        "Best available", "1080p", "720p", "480p", "360p"]
    assert combo.GetStringSelection() == "1080p"


def test_choice_is_saved_and_shown_again(panel):
    make, config = panel
    p = make()
    p.youtube_quality_combo.SetStringSelection("360p")
    p.onSave()
    assert config.get("playback.youtube_quality") == "360p"
    p.youtube_quality_combo.SetStringSelection("Best available")
    p.onSave()
    assert config.get("playback.youtube_quality") == "best"
    assert make().youtube_quality_combo.GetStringSelection() == "Best available"


def test_an_unrecognised_saved_value_shows_the_default(panel):
    make, config = panel
    config.set("playback.youtube_quality", value="8k")
    assert make().youtube_quality_combo.GetStringSelection() == "1080p"
