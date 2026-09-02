"""Tab-order regression tests for MainWindow.

Every composite panel here (SearchBar, wx.Listbook, NowPlayingBar) is its
own wx.Panel, and wx does NOT automatically escape Tab from a nested panel
up to the next sibling -- confirmed empirically, including with
TAB_TRAVERSAL passed to the Frame's constructor. Without explicit
boundary handling, Tab wraps forever inside whichever panel has focus
instead of ever reaching the next one. This has regressed multiple times
(premature escapes hijacking in-panel moves, NavigateIn() silently
skipping over the Listbook entirely, a missing SearchBar boundary leaving
it impossible to ever reach the listbook at all) -- these tests drive the
same wx.Window.Navigate() calls wx's own keyboard handling makes for a
real Tab press, without needing a running MainLoop or OS-level input.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
import wx
import wx.adv

from radiomaster.app import RadioMasterApp
from radiomaster.services.station_api import Station
from radiomaster.ui.help_dialog import (
    QUICK_START_TOPICS,
    RELEASE_NOTES_TOPICS,
    USER_MANUAL_TOPICS,
)


@pytest.fixture
def app_and_window():
    app = RadioMasterApp()
    win = app._main_window
    # First/Previous/Next/Last are correctly greyed out (and therefore
    # Tab-skipped) until there's station history to navigate -- exactly
    # what a fresh app start looks like. These tab-order tests care about
    # the *order*, not button-enabled-state (that's covered separately in
    # test_playback_engine.py's history tests), so give the transport bar
    # some history up front to put it in its normal, fully-focusable state.
    win._radio_panel._push_history(Station(uuid="a", name="A", url="http://a"))
    win._radio_panel._push_history(Station(uuid="b", name="B", url="http://b"))
    win._radio_panel._push_history(Station(uuid="c", name="C", url="http://c"))
    win._radio_panel._history_index = 1  # middle: both Previous and Next have somewhere to go
    win._update_transport_button_states()
    yield app, win
    win._lyrics_timer.Stop()
    win.Destroy()
    app.OnExit()


def _nav(win: wx.Window, forward: bool) -> wx.Window:
    f = win.FindFocus()
    f.Navigate(wx.NavigationKeyEvent.IsForward if forward else wx.NavigationKeyEvent.IsBackward)
    return win.FindFocus()


class TestHelpSystem:
    def test_help_menu_has_requested_order(self, app_and_window) -> None:
        """Manual is first, update check is second-last, and About is last."""
        _app, win = app_and_window
        menu_bar = win.GetMenuBar()
        help_menu = menu_bar.GetMenu(menu_bar.FindMenu("Help"))
        labels = [
            item.GetItemLabelText()
            for item in help_menu.GetMenuItems()
            if not item.IsSeparator()
        ]
        assert labels == [
            "User Manual",
            "Quick Start Guide",
            "Release Notes",
            "Update YouTube Library...",
            "Check for Updates...",
            "About RadioMaster+",
        ]

    def test_manual_covers_every_main_tab_and_core_reference_area(self) -> None:
        titles = {title for title, _body in USER_MANUAL_TOPICS}
        assert {
            "Radio Tab",
            "Podcasts Tab",
            "Audiobooks Tab",
            "Media Player Tab",
            "YouTube Tab",
            "Downloads Tab",
            "Scheduler Tab",
            "Settings",
            "Accessibility Notes",
            "Troubleshooting",
        } <= titles
        assert len(QUICK_START_TOPICS) >= 5
        from radiomaster import __version__
        assert RELEASE_NOTES_TOPICS[0][0] == f"Version {__version__}"


class TestPanelControls:
    def test_startup_settings_skip_duplicate_panel_refreshes(self, app_and_window) -> None:
        """Large panel collections are already loaded by their constructors."""
        _app, win = app_and_window
        with patch.object(win._radio_panel, "_apply_sections") as radio_refresh, \
             patch.object(win._podcast_panel, "refresh_episode_order") as podcast_refresh, \
             patch.object(win._youtube_panel, "refresh_download_settings") as youtube_refresh:
            win._apply_settings_changes(refresh_panels=False)

        radio_refresh.assert_not_called()
        podcast_refresh.assert_not_called()
        youtube_refresh.assert_not_called()

    def test_audiobook_uses_chapter_activation_without_play_button(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        assert not hasattr(win._audiobook_panel, "_btn_play")

    def test_scheduler_has_no_redundant_panel_date_or_time_picker(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        assert not hasattr(win._scheduler_panel, "_date_picker")
        assert not hasattr(win._scheduler_panel, "_time_picker")

    def test_audiobook_has_browse_file_button(self, app_and_window) -> None:
        _app, win = app_and_window
        assert win._audiobook_panel._btn_browse_file.GetLabel() == "Browse File..."

    def test_media_folder_populates_visible_playlist(
        self, app_and_window, tmp_path
    ) -> None:
        _app, win = app_and_window
        (tmp_path / "one.mp3").touch()
        nested = tmp_path / "disc two"
        nested.mkdir()
        (nested / "two.FLAC").touch()
        (nested / "notes.txt").touch()

        count = win._media_panel.load_folder(str(tmp_path))

        assert count == 2
        assert win._media_panel._playlist.GetItemCount() == 2
        assert len(win._media_panel._paths) == 2

    def test_media_uses_playlist_activation_without_play_button(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        assert not hasattr(win._media_panel, "_btn_play")


class TestGeneralSettings:
    def test_general_controls_are_named_and_offer_real_themes(self, app_and_window) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(win, win._config, theme_manager=win._theme_manager)
        try:
            panel = dlg._panel_map[0]
            assert panel.lang_combo.GetName() == "Language (applies after restart)"
            assert panel.theme_combo.GetName() == "Theme"
            assert panel.font_size_spin.GetName() == "Font Size"
            assert panel.theme_combo.GetItems() == win._theme_manager.get_theme_names()
            assert "Show system tray notification" in panel.show_notifications_chk.GetLabel()
        finally:
            dlg.Destroy()

    def test_general_panel_saves_theme_key_not_display_label(self, app_and_window) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        original = win._config.get("general.theme", default="default")
        dlg = SettingsDialog(win, win._config, theme_manager=win._theme_manager)
        try:
            panel = dlg._panel_map[0]
            dark_index = panel._theme_keys.index("dark")
            panel.theme_combo.SetSelection(dark_index)
            panel.onSave()
            assert win._config.get("general.theme") == "dark"
        finally:
            win._config.set("general.theme", value=original)
            dlg.Destroy()

    def test_apply_button_invokes_live_settings_callback(self, app_and_window) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        on_apply = MagicMock()
        dlg = SettingsDialog(
            win, win._config, theme_manager=win._theme_manager, on_apply=on_apply
        )
        try:
            dlg._save_all = MagicMock()
            with patch("radiomaster.ui.settings_dialog.wx.MessageBox"):
                dlg._on_apply(None)
            dlg._save_all.assert_called_once_with()
            on_apply.assert_called_once_with()
        finally:
            dlg.Destroy()


class TestPlaybackSettings:
    def test_playback_controls_save_every_setting_and_link_is_actionable(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        original = {
            key: win._config.get(f"playback.{key}")
            for key in (
                "output_device", "crossfade_duration", "gapless", "replaygain",
                "normalize_audio", "remember_position", "acoustid_api_key",
            )
        }
        dlg = SettingsDialog(win, win._config, theme_manager=win._theme_manager)
        try:
            dlg._switch_to(1)
            panel = dlg._panel_map[1]
            panel.output_device_combo.SetSelection(0)
            panel.crossfade_spin.SetValue(4)
            panel.gapless_chk.SetValue(True)
            panel.replaygain_combo.SetStringSelection("Track")
            panel.normalize_chk.SetValue(True)
            panel.remember_pos_chk.SetValue(False)
            panel.acoustid_key_txt.SetValue(" test-key ")
            panel.onSave()

            assert panel.crossfade_spin.GetName() == "Crossfade Duration (seconds)"
            assert panel.replaygain_combo.GetName() == "ReplayGain mode"
            links = [child for child in panel.GetChildren() if isinstance(child, wx.adv.HyperlinkCtrl)]
            assert len(links) == 1
            assert links[0].GetURL() == "https://acoustid.org/api-key"
            assert win._config.get("playback.output_device") == ""
            assert win._config.get("playback.crossfade_duration") == 4
            assert win._config.get("playback.gapless") is True
            assert win._config.get("playback.replaygain") == "track"
            assert win._config.get("playback.normalize_audio") is True
            assert win._config.get("playback.remember_position") is False
            assert win._config.get("playback.acoustid_api_key") == "test-key"
        finally:
            for key, value in original.items():
                win._config.set(f"playback.{key}", value=value)
            dlg.Destroy()

    def test_playlist_crossfade_starts_before_natural_end(self, app_and_window) -> None:
        _app, win = app_and_window
        panel = win._media_panel
        config = win._config
        old_fade = config.get("playback.crossfade_duration")
        old_gapless = config.get("playback.gapless")
        old_paths = panel._paths
        old_index = panel._current_index
        try:
            panel._paths = ["first.mp3", "second.mp3"]
            panel._current_index = 0
            panel._playlist.DeleteAllItems()
            panel._playlist.InsertItem(0, "First")
            panel._playlist.InsertItem(1, "Second")
            config.set("playback.crossfade_duration", value=3)
            config.set("playback.gapless", value=False)
            win._engine._current_url = "first.mp3"
            win._engine.crossfade_to = MagicMock()

            assert panel.try_crossfade_advance(96.5, 100.0) is False
            assert panel.try_crossfade_advance(97.0, 100.0) is True
            win._engine.crossfade_to.assert_called_once()
            assert panel._current_index == 1
        finally:
            config.set("playback.crossfade_duration", value=old_fade)
            config.set("playback.gapless", value=old_gapless)
            panel._paths = old_paths
            panel._current_index = old_index
            panel._playlist.DeleteAllItems()


class TestDownloadsSettings:
    def test_controls_are_named_and_formats_match_youtube(self, app_and_window) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(win, win._config, theme_manager=win._theme_manager)
        try:
            dlg._switch_to(4)
            panel = dlg._panel_map[4]
            assert panel.download_path_txt.GetName() == "Download Location"
            assert panel.max_concurrent_spin.GetName() == "Maximum Concurrent Downloads"
            assert panel.format_combo.GetName() == "Audio Format"
            assert panel.quality_combo.GetName() == "Audio Quality"
            assert panel.format_combo.GetItems() == [
                item.upper() for item in win._youtube_panel._audio_format_choices
            ]
        finally:
            dlg.Destroy()

    def test_live_apply_updates_manager_and_youtube_format(self, app_and_window) -> None:
        app, win = app_and_window
        old_max = win._config.get("downloads.max_concurrent", default=3)
        old_format = win._config.get("downloads.audio_format", default="mp3")
        original_set_max = app.download_manager.set_max_concurrent
        try:
            win._config.set("downloads.max_concurrent", value=4)
            win._config.set("downloads.audio_format", value="flac")
            app.download_manager.set_max_concurrent = MagicMock()

            with patch.object(win._config, "load"):
                win._apply_settings_changes()

            app.download_manager.set_max_concurrent.assert_called_with(4)
            assert win._youtube_panel._audio_format_choice.GetStringSelection() == "flac"
        finally:
            app.download_manager.set_max_concurrent = original_set_max
            win._config.set("downloads.max_concurrent", value=old_max)
            win._config.set("downloads.audio_format", value=old_format)
            win._youtube_panel.refresh_download_settings()


class TestRecordingsSettings:
    def test_controls_are_named_and_only_applicable_options_are_enabled(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(win, win._config, theme_manager=win._theme_manager)
        try:
            dlg._switch_to(5)
            panel = dlg._panel_map[5]
            assert panel.recording_path_txt.GetName() == "Recording Location"
            assert panel.rec_format_combo.GetName() == "Recording Format"
            assert panel.rec_quality_combo.GetName() == "Recording Quality"

            panel.match_source_chk.SetValue(False)
            panel.rec_format_combo.SetStringSelection("FLAC")
            panel._update_recording_option_states()
            assert panel.rec_format_combo.IsEnabled() is True
            assert panel.rec_quality_combo.IsEnabled() is False

            panel.rec_format_combo.SetStringSelection("MP3")
            panel._update_recording_option_states()
            assert panel.rec_quality_combo.IsEnabled() is True

            panel.match_source_chk.SetValue(True)
            panel._update_recording_option_states()
            assert panel.rec_format_combo.IsEnabled() is False
            assert panel.rec_quality_combo.IsEnabled() is False
            assert "Best" in panel.rec_quality_combo.GetItems()

            assert panel.skip_short_ads_chk.IsChecked() is True
            assert panel.ad_max_duration_spin.GetValue() == 30
            assert panel.ad_max_duration_spin.GetName() == (
                "Maximum likely advertisement duration in seconds"
            )
            panel.skip_short_ads_chk.SetValue(False)
            panel._update_ad_detection_states()
            assert panel.ad_max_duration_spin.IsEnabled() is False
            panel.skip_short_ads_chk.SetValue(True)
            panel.split_tracks_chk.SetValue(False)
            panel._update_ad_detection_states()
            assert panel.skip_short_ads_chk.IsEnabled() is False
        finally:
            dlg.Destroy()


class TestNetworkSettings:
    def test_controls_are_named_and_proxy_dependencies_are_truthful(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(win, win._config, theme_manager=win._theme_manager)
        try:
            dlg._switch_to(6)
            panel = dlg._panel_map[6]
            assert panel.proxy_host_txt.GetName() == "Proxy Host"
            assert panel.proxy_port_spin.GetName() == "Proxy Port"
            assert panel.timeout_spin.GetName() == "Connection Timeout in seconds"
            assert panel.user_agent_txt.GetName() == (
                "Custom User Agent; blank uses the application default"
            )

            panel.proxy_enabled_chk.SetValue(False)
            panel._update_proxy_control_states()
            assert panel.proxy_host_txt.IsEnabled() is False
            assert panel.proxy_port_spin.IsEnabled() is False
            panel.proxy_enabled_chk.SetValue(True)
            panel._update_proxy_control_states()
            assert panel.proxy_host_txt.IsEnabled() is True
            assert panel.proxy_port_spin.IsEnabled() is True
        finally:
            dlg.Destroy()


class TestAccessibilitySettings:
    def test_accessibility_options_are_wired_and_apply_immediately(
        self, app_and_window
    ) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        original_high_contrast = win._config.get("accessibility.high_contrast", default=False)
        original_dyslexia_font = win._config.get("accessibility.dyslexia_font", default=False)
        original_extras = {
            key: win._config.get(f"accessibility.{key}", default=default)
            for key, default in (
                ("screen_reader_optimized", True),
                ("keyboard_navigation", True),
                ("focus_indicators", True),
                ("reduce_motion", False),
            )
        }
        dlg = SettingsDialog(
            win, win._config, theme_manager=win._theme_manager,
            on_apply=win._apply_settings_changes,
        )
        try:
            dlg._switch_to(7)
            panel = dlg._panel_map[7]
            assert panel.high_contrast_chk.GetLabelText() == (
                "Use black and white high contrast colors"
            )
            assert panel.dyslexia_font_chk.GetLabelText() == (
                "Use OpenDyslexic font when installed"
            )
            panel.screen_reader_chk.SetValue(False)
            panel.keyboard_nav_chk.SetValue(False)
            panel.focus_indicators_chk.SetValue(False)
            panel.reduce_motion_chk.SetValue(True)

            panel.high_contrast_chk.SetValue(True)
            panel.dyslexia_font_chk.SetValue(True)
            dlg._save_all()
            win._apply_settings_changes()
            assert win._config.get("accessibility.high_contrast") is True
            assert win._config.get("accessibility.dyslexia_font") is True
            assert win._config.get("accessibility.screen_reader_optimized") is False
            assert win._config.get("accessibility.keyboard_navigation") is False
            assert win._config.get("accessibility.focus_indicators") is False
            assert win._config.get("accessibility.reduce_motion") is True
            assert win._status_bar._announcements_enabled is False
            assert win.GetBackgroundColour() == wx.Colour(0, 0, 0)
            assert win.GetForegroundColour() == wx.Colour(255, 255, 255)
        finally:
            win._config.set(
                "accessibility.high_contrast", value=original_high_contrast
            )
            win._config.set(
                "accessibility.dyslexia_font", value=original_dyslexia_font
            )
            for key, value in original_extras.items():
                win._config.set(f"accessibility.{key}", value=value)
            win._config.save()
            win._apply_settings_changes()
            dlg.Destroy()

    def test_f6_cycles_major_regions_when_enabled(self, app_and_window) -> None:
        _app, win = app_and_window
        original = win._config.get("accessibility.keyboard_navigation", default=True)
        try:
            win._config.set("accessibility.keyboard_navigation", value=True)
            win._search_bar._search_ctrl.SetFocus()
            wx.Yield()
            win._cycle_focus_region()
            wx.Yield()
            assert wx.Window.FindFocus() == win._listbook.GetListView()
            win._cycle_focus_region(backward=True)
            wx.Yield()
            focus = wx.Window.FindFocus()
            assert focus == win._search_bar._search_ctrl or (
                focus and focus.GetParent() == win._search_bar._search_ctrl
            )
        finally:
            win._config.set("accessibility.keyboard_navigation", value=original)

    def test_status_announcements_are_deduplicated(self, app_and_window) -> None:
        _app, win = app_and_window
        bar = win._status_bar
        with patch.object(wx.Accessible, "NotifyEvent") as notify:
            bar.set_screen_reader_announcements(True)
            bar.set_status("Accessibility test")
            bar.set_status("Accessibility test")
        notify.assert_called_once()
        assert bar._accessible.GetName(0) == (wx.ACC_OK, "Status: Accessibility test")


class TestSharedContentPane:
    def test_podcast_selection_shows_plain_text_notes(self, app_and_window) -> None:
        _app, win = app_and_window
        panel = win._podcast_panel
        panel._current_podcast_title = "Example Podcast"
        panel._episode_data = [{
            "title": "Episode One", "published_date": "2026-09-02",
            "duration": 125, "description": "<p>Hello <strong>listener</strong>.</p>",
        }]
        panel._episode_list.DeleteAllItems()
        panel._episode_list.InsertItem(0, "Episode One")
        panel._episode_list.Select(0)
        panel.show_selected_notes()

        value = win._lyrics_panel._text_ctrl.GetValue()
        assert "Episode One" in value
        assert "Example Podcast" in value
        assert "Hello listener" in value
        assert "<strong>" not in value

    def test_youtube_selection_shows_video_information(self, app_and_window) -> None:
        _app, win = app_and_window
        panel = win._youtube_panel
        panel._search_results = [{
            "title": "Accessible Video", "channel": "Example Channel",
            "duration": 65, "view_count": 1234, "description": "Video description",
        }]
        panel._results_list.DeleteAllItems()
        row = panel._results_list.InsertItem(0, "Accessible Video")
        panel._results_list.SetItemData(row, 0)
        panel._results_list.Select(row)
        panel.show_selected_info()

        value = win._lyrics_panel._text_ctrl.GetValue()
        assert "Accessible Video" in value
        assert "Channel: Example Channel" in value
        assert "Duration: 1:05" in value
        assert "Views: 1,234" in value
        assert "Video description" in value


class TestAdvancedSettings:
    def test_logging_modes_and_ytdlp_option_save_and_apply(self, app_and_window) -> None:
        _app, win = app_and_window
        from radiomaster.ui.settings_dialog import SettingsDialog

        original_level = win._config.get("logging.level", default="info")
        original_auto = win._config.get("updates.ytdlp_auto_update", default=True)
        dlg = SettingsDialog(win, win._config, on_apply=win._apply_settings_changes)
        try:
            dlg._switch_to(8)
            panel = dlg._panel_map[8]
            assert panel.logging_combo.GetName() == "Logging Level"
            assert panel._log_level_values == ["off", "info", "debug", "io"]

            for index, expected in enumerate(panel._log_level_values):
                panel.logging_combo.SetSelection(index)
                win._config.set("logging.level", value="different")
                with patch("radiomaster.utils.logging_setup.setup_logging") as setup:
                    panel.onSave()
                assert win._config.get("logging.level") == expected
                setup.assert_called_once_with(level=expected, log_dir=win._paths["logs"])

            panel.ytdlp_auto_update_chk.SetValue(False)
            panel.onSave()
            assert win._config.get("updates.ytdlp_auto_update") is False
        finally:
            win._config.set("logging.level", value=original_level)
            win._config.set("updates.ytdlp_auto_update", value=original_auto)
            win._config.save()
            dlg.Destroy()

    def test_enabling_due_ytdlp_update_applies_without_restart(self, app_and_window) -> None:
        _app, win = app_and_window
        original_auto = win._config.get("updates.ytdlp_auto_update", default=True)
        original_last = win._config.get("updates.ytdlp_last_check_timestamp", default=0)
        try:
            win._config.set("updates.ytdlp_auto_update", value=True)
            win._config.set("updates.ytdlp_last_check_timestamp", value=0)
            with patch.object(win, "_auto_update_ytdlp") as update:
                win._maybe_auto_update_ytdlp()
            update.assert_called_once_with()

            win._config.set("updates.ytdlp_auto_update", value=False)
            with patch.object(win, "_auto_update_ytdlp") as update:
                win._maybe_auto_update_ytdlp()
            update.assert_not_called()
        finally:
            win._config.set("updates.ytdlp_auto_update", value=original_auto)
            win._config.set("updates.ytdlp_last_check_timestamp", value=original_last)
            win._config.save()


class TestRadioSettings:
    def test_radio_controls_save_all_runtime_settings(self, app_and_window) -> None:
        _app, win = app_and_window
        from radiomaster.services.station_update_scheduler import FREQUENCIES
        from radiomaster.ui.settings_dialog import SettingsDialog

        keys = (
            "default_country", "show_duplicates", "auto_reconnect",
            "reconnect_max_attempts", "reconnect_interval",
            "auto_play_last_station", "station_update_frequency",
        )
        original = {key: win._config.get(f"radio.{key}") for key in keys}
        dlg = SettingsDialog(
            win, win._config, station_updater=win._station_updater,
            on_station_update=win._radio_panel.refresh_after_station_update,
            theme_manager=win._theme_manager,
        )
        try:
            dlg._switch_to(2)
            panel = dlg._panel_map[2]
            panel.country_combo.SetStringSelection("Canada")
            panel.show_duplicates_chk.SetValue(True)
            panel.auto_reconnect_chk.SetValue(False)
            panel._sync_reconnect_controls()
            assert panel.reconnect_attempts_spin.IsEnabled() is False
            assert panel.reconnect_interval_spin.IsEnabled() is False
            panel.auto_reconnect_chk.SetValue(True)
            panel._sync_reconnect_controls()
            panel.reconnect_attempts_spin.SetValue(8)
            panel.reconnect_interval_spin.SetValue(4)
            panel.auto_play_last_chk.SetValue(True)
            panel.update_freq_choice.SetSelection(FREQUENCIES.index("monthly"))
            panel.onSave()

            assert panel.country_combo.GetName() == "Default Country"
            assert panel.reconnect_attempts_spin.GetName() == "Reconnect attempts before giving up"
            assert panel.reconnect_interval_spin.GetName() == (
                "Interval between reconnect attempts (seconds)"
            )
            assert panel.update_now_status.GetName() == "Station list update status"
            assert panel.station_updater is win._station_updater
            assert panel.on_station_update == win._radio_panel.refresh_after_station_update
            assert win._config.get("radio.default_country") == "canada"
            assert win._config.get("radio.show_duplicates") is True
            assert win._config.get("radio.auto_reconnect") is True
            assert win._config.get("radio.reconnect_max_attempts") == 8
            assert win._config.get("radio.reconnect_interval") == 4.0
            assert win._config.get("radio.auto_play_last_station") is True
            assert win._config.get("radio.station_update_frequency") == "monthly"
        finally:
            for key, value in original.items():
                win._config.set(f"radio.{key}", value=value)
            dlg.Destroy()

    def test_applying_radio_settings_updates_live_consumers(self, app_and_window) -> None:
        _app, win = app_and_window
        win._engine.set_auto_reconnect = MagicMock()
        win._engine.set_reconnect_settings = MagicMock()
        win._radio_panel._apply_sections = MagicMock()
        win._station_update_scheduler.set_frequency = MagicMock()

        win._apply_settings_changes()

        win._engine.set_auto_reconnect.assert_called_once_with(
            win._config.get("radio.auto_reconnect")
        )
        win._engine.set_reconnect_settings.assert_called_once_with(
            win._config.get("radio.reconnect_max_attempts"),
            win._config.get("radio.reconnect_interval"),
        )
        win._radio_panel._apply_sections.assert_called_once_with()
        win._station_update_scheduler.set_frequency.assert_called_once_with(
            win._config.get("radio.station_update_frequency")
        )


class TestTabOrder:
    def test_forward_chain_reaches_listbook_and_transport_bar(self, app_and_window) -> None:
        """search bar -> listbook tab list -> Radio page's own controls, in
        order, with nothing skipped -> transport bar. This exact chain has
        broken three different ways in the past (see module docstring)."""
        app, win = app_and_window
        win._search_bar.SetFocus()
        assert type(win.FindFocus()).__name__ == "SearchCtrl"

        assert type(_nav(win, True)).__name__ == "Choice"
        assert type(_nav(win, True)).__name__ == "Button"  # search bar's Go button

        # Escaping the search bar must land in the listbook's tab list --
        # not skip over it into the transport bar (NavigateIn() did this).
        listbook_entry = _nav(win, True)
        assert listbook_entry is win._listbook.GetListView()

        # Walking forward through the Radio page's own controls must visit
        # each one -- not jump straight to the transport bar (an
        # over-broad escape guard did this) and not loop forever inside
        # the page (an under-broad one did this).
        seen_classes = []
        focus = listbook_entry
        # 9, not 10 -- one fewer stop since the Radio tab's "Refresh
        # Database" button was removed (its equivalent now lives as
        # "Update Now" in Settings > Radio instead).
        for _ in range(9):
            focus = _nav(win, True)
            seen_classes.append(type(focus).__name__)
        assert "_VirtualStationList" in seen_classes, (
            f"station list was skipped over entirely: {seen_classes}"
        )
        assert seen_classes[-1] == "Button" and focus.GetLabel() == "|◀", (
            f"did not land on the transport bar's first control (First Track): {seen_classes}"
        )

    def test_backward_chain_returns_to_search_bar(self, app_and_window) -> None:
        """Shift+Tab from deep in the transport bar must walk back into the
        Radio page's content (not get stranded outside the listbook with
        no way back in -- the original, most literally reported bug:
        'you cannot get back to the list of stations') and, continuing
        further, eventually reach the search bar again."""
        app, win = app_and_window
        win._now_playing._btn_mute.SetFocus()

        seen_classes = []
        seen_pages = []
        for _ in range(30):
            focus = _nav(win, False)
            seen_classes.append(type(focus).__name__)
            # Landing inside the Radio page's own widget tree (not just on
            # the listbook's tab list, which wx reaches independently of
            # whether re-entering the page's content actually worked).
            seen_pages.append(_is_descendant_of(focus, win._radio_panel))

        assert any(seen_pages), (
            f"Shift+Tab off the transport bar never re-entered the Radio "
            f"page's own content, only escaped past it: {seen_classes}"
        )
        assert "SearchCtrl" in seen_classes, (
            f"never made it all the way back to the search bar: {seen_classes}"
        )


class TestStationHistory:
    """RadioPanel's station history (Previous/Next/First/Last on the
    transport bar) and the transport-bar greying that goes with it."""

    def _reset(self, win) -> None:
        # The fixture pre-populates history for the tab-order tests above;
        # start these from a clean slate instead.
        win._radio_panel._history = []
        win._radio_panel._history_index = -1
        win._update_transport_button_states()
        # history_previous()/first()/last() call through to _play_station(),
        # which would otherwise spawn real background threads trying to
        # open fake "http://a"-style URLs -- these tests are only checking
        # the history list/index bookkeeping and button states, not real
        # playback, so stub out the actual engine/API calls.
        win._radio_panel.engine.play = MagicMock()
        win._radio_panel.station_api.click = MagicMock()

    def test_fresh_station_appends_and_becomes_current(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel

        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="b", name="B", url="http://b"))

        assert [s.uuid for s in panel._history] == ["a", "b"]
        assert panel._history_index == 1
        assert panel.history_has_previous() is True
        assert panel.history_has_next() is False

    def test_reactivating_current_station_is_a_noop(self, app_and_window) -> None:
        """Double-clicking the station that's already playing shouldn't
        add a duplicate history entry."""
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel

        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="a", name="A", url="http://a"))

        assert len(panel._history) == 1

    def test_picking_fresh_station_after_going_back_truncates_forward_history(
        self, app_and_window
    ) -> None:
        """Browser-style: Previous, Previous, then picking a new station
        should discard the stations that were ahead of where you went
        back to, not just append after them."""
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel

        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="b", name="B", url="http://b"))
        panel._push_history(Station(uuid="c", name="C", url="http://c"))
        panel.history_previous()
        panel.history_previous()
        assert panel._history_index == 0

        panel._push_history(Station(uuid="d", name="D", url="http://d"))

        assert [s.uuid for s in panel._history] == ["a", "d"]
        assert panel._history_index == 1

    def test_first_last_jump_to_the_ends(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel
        for uuid in ("a", "b", "c", "d"):
            panel._push_history(Station(uuid=uuid, name=uuid.upper(), url=f"http://{uuid}"))
        assert panel._history_index == 3

        panel.history_first()
        assert panel._history_index == 0
        assert panel.history_has_previous() is False
        assert panel.history_has_next() is True

        panel.history_last()
        assert panel._history_index == 3
        assert panel.history_has_previous() is True
        assert panel.history_has_next() is False

    def test_previous_next_are_noop_at_the_ends(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel
        panel._push_history(Station(uuid="a", name="A", url="http://a"))

        panel.history_previous()  # already at (only) entry -- no previous
        assert panel._history_index == 0
        panel.history_next()  # already at (only) entry -- no next
        assert panel._history_index == 0

    def test_transport_buttons_grey_out_with_no_history(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        assert win._now_playing._btn_first.IsEnabled() is False
        assert win._now_playing._btn_prev.IsEnabled() is False
        assert win._now_playing._btn_next.IsEnabled() is False
        assert win._now_playing._btn_last.IsEnabled() is False

    def test_transport_buttons_enable_once_there_is_somewhere_to_go(self, app_and_window) -> None:
        app, win = app_and_window
        self._reset(win)
        panel = win._radio_panel
        panel._push_history(Station(uuid="a", name="A", url="http://a"))
        panel._push_history(Station(uuid="b", name="B", url="http://b"))
        panel._push_history(Station(uuid="c", name="C", url="http://c"))
        panel.history_previous()  # now on "b", the true middle -- both directions available
        win._update_transport_button_states()

        assert win._now_playing._btn_first.IsEnabled() is True
        assert win._now_playing._btn_prev.IsEnabled() is True
        assert win._now_playing._btn_next.IsEnabled() is True
        assert win._now_playing._btn_last.IsEnabled() is True

    def test_seek_controls_grey_out_for_unseekable_radio_stream(self, app_and_window) -> None:
        """Radio streams always have duration == 0 (no fixed timeline) --
        Fast Forward/Rewind/the position slider must be disabled, not just
        silently do nothing when clicked."""
        app, win = app_and_window
        assert win._engine.duration == 0
        win._update_transport_button_states()

        assert win._now_playing._btn_ffwd.IsEnabled() is False
        assert win._now_playing._btn_rewind.IsEnabled() is False
        assert win._now_playing._position_slider.IsEnabled() is False

    def test_stop_greyed_out_when_nothing_is_playing(self, app_and_window) -> None:
        """Nothing to stop before anything's ever been played -- Stop had
        no enabled/disabled logic at all before this, so it was always
        clickable even with the engine in STATE_STOPPED."""
        app, win = app_and_window
        assert win._engine.state == "stopped"
        win._update_transport_button_states()
        assert win._now_playing._btn_stop.IsEnabled() is False

    def test_stop_enables_once_something_is_playing(self, app_and_window) -> None:
        app, win = app_and_window
        for state in ("playing", "paused", "buffering"):
            win._now_playing.set_stoppable(state != "stopped")
            assert win._now_playing._btn_stop.IsEnabled() is True, state
        win._now_playing.set_stoppable("stopped" != "stopped")
        assert win._now_playing._btn_stop.IsEnabled() is False


def _is_descendant_of(window: wx.Window, ancestor: wx.Window) -> bool:
    w = window
    while w is not None:
        if w is ancestor:
            return True
        w = w.GetParent()
    return False


class TestLyricsFetch:
    """engine._current_title/_current_artist previously only ever held
    the station's own name and an empty artist (set once at play() time),
    which no lyrics provider could match against anything -- lyrics never
    showed up for radio. _on_radio_now_playing_changed (wired to
    RadioPanel.on_now_playing_changed, fired from parsed ICY metadata) is
    what actually gives the engine the real song."""

    def test_now_playing_change_updates_engine_track_info(self, app_and_window) -> None:
        app, win = app_and_window
        win._engine._current_title = "My Station Name"
        win._engine._current_artist = ""

        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None):
            win._on_radio_now_playing_changed("Real Artist", "Real Song")

        assert win._engine._current_artist == "Real Artist"
        assert win._engine._current_title == "Real Song"

    def test_now_playing_change_captures_song_start_offset(self, app_and_window) -> None:
        """A radio station's play() only ever runs once, when it's tuned
        in -- engine.position keeps counting from then, not from when a
        song heard partway through the stream actually started. Without
        capturing an offset at the moment the song is detected, LRC
        highlighting would compare against "seconds since tuned in"
        instead of "seconds into this song" and jump straight to the
        last line."""
        app, win = app_and_window
        win._engine._live._position = 1200.0  # 20 minutes into the station
        win._lyrics_song_start_position = 0.0

        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None):
            win._on_radio_now_playing_changed("Real Artist", "Real Song")

        assert win._lyrics_song_start_position == 1200.0

    def test_lyrics_timer_highlights_relative_to_song_start(self, app_and_window) -> None:
        app, win = app_and_window
        win._engine._live._state = "playing"
        win._lyrics_song_start_position = 1200.0
        win._lyrics_panel._lrc_lines = [(0.0, "line zero"), (5.0, "line five"), (10.0, "line ten")]
        win._lyrics_panel.highlight_sentence = MagicMock()

        # 3s into the song -> raw engine position is 1203, well past every
        # LRC timestamp; only the offset-adjusted value (3.0) picks line 0.
        win._engine._live._position = 1203.0
        win._on_lyrics_timer(None)
        win._lyrics_panel.highlight_sentence.assert_called_with(0)

        win._engine._live._position = 1207.0
        win._on_lyrics_timer(None)
        win._lyrics_panel.highlight_sentence.assert_called_with(1)

    def test_new_track_resets_song_start_offset_to_zero(self, app_and_window) -> None:
        """Local files/podcasts/etc: play() itself is the song starting,
        so engine.position is already correct with no offset -- a leftover
        nonzero offset from a previous radio session must not leak in."""
        app, win = app_and_window
        win._lyrics_song_start_position = 1200.0
        win._engine._current_title = "Some Local Track"
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None):
            win._on_engine_state("playing")
        assert win._lyrics_song_start_position == 0.0

    def test_fetch_lyrics_uses_lrc_key_not_the_old_wrong_keys(self, app_and_window) -> None:
        """Regression test for the exact bug that silently broke synced
        lyrics: LyricsService.fetch_lyrics() returns synced lyrics under
        the "lrc" key, but the caller used to read "lyrics_synced"/
        "lrc_data" instead, which never existed in the actual result."""
        app, win = app_and_window
        win._engine._current_artist = "Real Artist"
        win._engine._current_title = "Real Song"

        fake_result = {"lyrics": "line one\nline two", "lrc": "[00:01.00]line one\n[00:05.00]line two"}
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=fake_result):
            win._fetch_lyrics_for_current()
            deadline = time.time() + 3
            while time.time() < deadline and not getattr(win._lyrics_panel, "_lrc_lines", None):
                wx.Yield()
                time.sleep(0.05)

        assert win._lyrics_panel._lrc_lines == [(1.0, "line one"), (5.0, "line two")]

    def test_fetch_lyrics_skipped_when_no_title(self, app_and_window) -> None:
        app, win = app_and_window
        win._engine._current_title = ""
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics") as mock_fetch:
            win._fetch_lyrics_for_current()
            wx.Yield()
        mock_fetch.assert_not_called()

    def test_rebuffer_state_does_not_refetch_same_track(self, app_and_window) -> None:
        """Recovering from an audio underrun is not a new song."""
        app, win = app_and_window
        win._engine._current_url = "https://radio.test/live"
        win._engine._current_artist = "Artist"
        win._engine._current_title = "Song"
        with patch("radiomaster.services.lyrics_service.LyricsService.fetch_lyrics", return_value=None) as fetch:
            win._on_engine_state("playing")
            win._on_engine_state("buffering")
            win._on_engine_state("playing")
            deadline = time.time() + 2
            while time.time() < deadline and fetch.call_count == 0:
                time.sleep(0.02)
        assert fetch.call_count == 1


class TestRecording:
    """The Record button's ffmpeg process genuinely started, but nothing
    ever told NowPlayingBar's "Record Off"/"Recording On" button -- with
    no other feedback, that was indistinguishable from the button doing
    nothing at all, especially for a screen-reader user relying on the
    button's own accessible name to know whether it worked."""

    def test_record_toggles_transport_bar_button_state(self, app_and_window) -> None:
        app, win = app_and_window
        panel = win._radio_panel
        panel._selected_station = Station(uuid="a", name="A", url="http://a")

        assert win._now_playing._btn_record.GetLabelText() == "● Record Off"

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.return_value = MagicMock()
            panel._on_record()
        assert win._now_playing._btn_record.GetLabelText() == "● Recording On"

        panel._on_record()  # toggle off
        assert win._now_playing._btn_record.GetLabelText() == "● Record Off"

    def test_stop_does_not_halt_an_active_recording(self, app_and_window) -> None:
        """Stop only stops playback -- a recording is a separate ffmpeg
        connection to the stream, and by design is only ever stopped by
        toggling Record off again, not by Stop."""
        app, win = app_and_window
        panel = win._radio_panel
        panel._selected_station = Station(uuid="a", name="A", url="http://a")
        panel.engine.stop = MagicMock()

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.return_value = MagicMock()
            panel._on_record()
        assert len(panel._recordings) == 1

        panel._on_stop()
        assert len(panel._recordings) == 1
        assert win._now_playing._btn_record.GetLabelText() == "● Recording On"

        panel._on_record()  # toggle off explicitly
        assert len(panel._recordings) == 0

    def test_active_recording_shows_in_downloads_panel(self, app_and_window) -> None:
        """A manual recording's ffmpeg process genuinely started, but the
        Downloads tab is where the user actually looks to confirm it's
        running -- without a "downloads" row, it never showed up there
        at all even while genuinely recording.

        Uses a distinctive station name and checks for that specific row
        rather than assuming the list is otherwise empty -- app_and_window
        uses the app's real (not test-isolated) SQLite database, which
        can carry rows over between runs.
        """
        app, win = app_and_window
        marker = f"DownloadsPanelTest-{id(self)}"
        panel = win._radio_panel
        panel._selected_station = Station(uuid="a", name=marker, url="http://a")

        def _row(list_ctrl, title):
            for i in range(list_ctrl.GetItemCount()):
                if list_ctrl.GetItemText(i, 0) == title:
                    return list_ctrl.GetItemText(i, 2)
            return None

        # This assertion covers the single-file recording row. Split-track
        # mode intentionally replaces it with one row per finalized track.
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        real_get = config.get
        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None), \
                patch.object(
                    config, "get",
                    side_effect=lambda *args, **kwargs: (
                        False
                        if args and args[0] == "recordings.split_tracks"
                        else real_get(*args, **kwargs)
                    ),
                ):
            mock_popen.return_value = MagicMock()
            panel._on_record()

        expected_title = f"Recording: {marker}"
        assert _row(win._downloads_panel._active_list, expected_title) == "downloading"

        panel._on_record()  # stop
        assert _row(win._downloads_panel._active_list, expected_title) is None
        assert _row(win._downloads_panel._history_list, expected_title) == "completed"

    def test_multiple_stations_can_record_independently(self, app_and_window) -> None:
        """The README (and the existing Recording Scheduler) promise
        multiple simultaneous recordings -- the original single-value
        self._record_process couldn't represent more than one at a time,
        so starting a second recording silently had no way to track the
        first one at all."""
        app, win = app_and_window
        panel = win._radio_panel
        station_a = Station(uuid="rec-a", name="Rec A", url="http://a")
        station_b = Station(uuid="rec-b", name="Rec B", url="http://b")

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.side_effect = lambda *a, **k: MagicMock()

            panel._selected_station = station_a
            panel._on_record()
            assert panel.is_station_recording(station_a) is True
            assert panel.is_station_recording(station_b) is False

            panel._selected_station = station_b
            panel._on_record()
            assert panel.is_station_recording(station_a) is True, (
                "starting B's recording must not stop A's"
            )
            assert panel.is_station_recording(station_b) is True
            assert len(panel._recordings) == 2

            # Stopping B (currently selected) must leave A running.
            panel._on_record()
            assert panel.is_station_recording(station_a) is True
            assert panel.is_station_recording(station_b) is False
            assert len(panel._recordings) == 1

    def test_record_button_reflects_the_currently_selected_station(self, app_and_window) -> None:
        """With multiple stations potentially recording at once, the
        button's state must track whichever station is now selected, not
        just whatever the last Record click happened to affect."""
        app, win = app_and_window
        panel = win._radio_panel
        station_a = Station(uuid="rec-a", name="Rec A", url="http://a")
        station_b = Station(uuid="rec-b", name="Rec B", url="http://b")

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.side_effect = lambda *a, **k: MagicMock()
            panel._selected_station = station_a
            panel._on_record()  # A is now recording

        panel.tree.get_selected_station = lambda: station_b
        panel._on_tree_sel_changed()
        assert win._now_playing._btn_record.GetLabelText() == "● Record Off"

        panel.tree.get_selected_station = lambda: station_a
        panel._on_tree_sel_changed()
        assert win._now_playing._btn_record.GetLabelText() == "● Recording On"

    def test_downloads_panel_stops_a_specific_recording(self, app_and_window) -> None:
        """The Downloads tab's "Stop Recording" button lets any active
        recording be stopped directly from there, without needing to
        first re-select that exact station back in the Radio tab."""
        app, win = app_and_window
        panel = win._radio_panel
        downloads = win._downloads_panel
        station_a = Station(uuid="rec-a", name="Rec A", url="http://a")
        station_b = Station(uuid="rec-b", name="Rec B", url="http://b")

        with patch("subprocess.Popen") as mock_popen, \
                patch("radiomaster.services.stream_prober.probe_stream_format", return_value=None):
            mock_popen.side_effect = lambda *a, **k: MagicMock()
            panel._selected_station = station_a
            panel._on_record()
            panel._selected_station = station_b
            panel._on_record()

        assert len(panel._recordings) == 2
        download_id = next(iter(panel._recordings))

        assert panel.stop_recording_by_download_id(download_id) is True
        assert len(panel._recordings) == 1
        assert download_id not in panel._recordings

        # A download_id that isn't (or is no longer) active reports False
        # instead of raising -- e.g. the Downloads panel's own guard
        # against a stale/already-stopped selection.
        assert panel.stop_recording_by_download_id(download_id) is False
