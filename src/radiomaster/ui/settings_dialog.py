"""Settings dialog with multi-category support following NVDA's pattern.

Uses a ``wx.ListCtrl`` on the left for categories and a ``ScrolledPanel``
on the right for the settings panel, exactly like NVDA's
``MultiCategorySettingsDialog``. Each category is a ``SettingsPanel``
subclass with ``makeSettings()``, ``onSave()``, and optional
``onPanelActivated()`` / ``onPanelDeactivated()`` methods.
"""

import wx
import wx.adv
from typing import Dict, Any, Optional, Type
import json

from ..utils.config import ConfigManager as Config
from ..utils.paths import get_paths
from ..utils.accessibility import set_accessible_name


# ---------------------------------------------------------------------------
# SettingsPanel base class  (analogous to NVDA's SettingsPanel)
# ---------------------------------------------------------------------------
class SettingsPanel(wx.Panel):
    """A single settings category panel.

    Subclasses must set ``title`` and override ``makeSettings()`` and
    ``onSave()``.
    """

    title: str = ""

    def __init__(self, parent: wx.Window, config: Config) -> None:
        super().__init__(parent)
        self.config = config
        self._setup()

    def _setup(self) -> None:
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.settings_sizer = wx.BoxSizer(wx.VERTICAL)
        self.makeSettings(self.settings_sizer)
        self.main_sizer.Add(self.settings_sizer, flag=wx.ALL | wx.EXPAND, border=8)
        self.main_sizer.Fit(self)
        self.SetSizer(self.main_sizer)

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        """Populate the panel with settings controls. Subclasses must override."""
        raise NotImplementedError

    def onSave(self) -> None:
        """Save settings from this panel. Subclasses must override."""
        raise NotImplementedError

    def onPanelActivated(self) -> None:
        """Called when this category is selected. Subclasses may extend."""
        self.Show()

    def onPanelDeactivated(self) -> None:
        """Called when another category is selected. Subclasses may extend."""
        self.Hide()

    def onDiscard(self) -> None:
        """Called when Cancel is pressed. Subclasses may extend."""
        pass


# ---------------------------------------------------------------------------
# Concrete panel implementations
# ---------------------------------------------------------------------------
class GeneralPanel(SettingsPanel):
    title = "General"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        # Language
        from radiomaster.i18n import LANGUAGES
        # LANGUAGES is keyed by the ISO code I18nManager actually uses
        # ("en", "es", ...) -- the combo shows display names but onSave()
        # below converts back to the code, so this list's order fixes the
        # code<->name mapping in both directions.
        self._lang_codes = list(LANGUAGES.keys())
        sizer.Add(wx.StaticText(self, label="Language:"), 0, wx.ALL, 5)
        self.lang_combo = wx.ComboBox(
            self, choices=[LANGUAGES[c] for c in self._lang_codes], style=wx.CB_READONLY,
        )
        current_code = self.config.get("general.language", default="en")
        if current_code not in LANGUAGES:
            current_code = "en"
        self.lang_combo.SetStringSelection(LANGUAGES[current_code])
        sizer.Add(self.lang_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Theme
        sizer.Add(wx.StaticText(self, label="Theme:"), 0, wx.ALL, 5)
        self.theme_combo = wx.ComboBox(self, choices=[
            "Default", "Dark", "Light", "High Contrast", "Custom",
        ], style=wx.CB_READONLY)
        self.theme_combo.SetStringSelection(
            self.config.get("general.theme", default="default").title()
        )
        sizer.Add(self.theme_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Font size
        sizer.Add(wx.StaticText(self, label="Font Size:"), 0, wx.ALL, 5)
        self.font_size_spin = wx.SpinCtrl(
            self, value=str(self.config.get("general.font_size", default=12)),
            min=8, max=24,
        )
        sizer.Add(self.font_size_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Startup options
        self.start_on_boot_chk = wx.CheckBox(self, label="Start on boot")
        self.start_on_boot_chk.SetValue(self.config.get("general.start_on_boot", default=False))
        sizer.Add(self.start_on_boot_chk, 0, wx.ALL, 5)

        self.minimize_to_tray_chk = wx.CheckBox(self, label="Minimize to system tray")
        self.minimize_to_tray_chk.SetValue(self.config.get("general.minimize_to_tray", default=True))
        sizer.Add(self.minimize_to_tray_chk, 0, wx.ALL, 5)

        self.close_to_tray_chk = wx.CheckBox(self, label="Close to system tray")
        self.close_to_tray_chk.SetValue(self.config.get("general.close_to_tray", default=False))
        sizer.Add(self.close_to_tray_chk, 0, wx.ALL, 5)

        self.show_notifications_chk = wx.CheckBox(self, label="Show notifications")
        self.show_notifications_chk.SetValue(self.config.get("general.show_notifications", default=True))
        sizer.Add(self.show_notifications_chk, 0, wx.ALL, 5)

    def onSave(self) -> None:
        from radiomaster.i18n import LANGUAGES
        selected_name = self.lang_combo.GetStringSelection()
        code = next((c for c in self._lang_codes if LANGUAGES[c] == selected_name), "en")
        self.config.set("general.language", value=code)
        self.config.set("general.theme", value=self.theme_combo.GetStringSelection().lower())
        self.config.set("general.font_size", value=self.font_size_spin.GetValue())
        self.config.set("general.start_on_boot", value=self.start_on_boot_chk.IsChecked())
        self.config.set("general.minimize_to_tray", value=self.minimize_to_tray_chk.IsChecked())
        self.config.set("general.close_to_tray", value=self.close_to_tray_chk.IsChecked())
        self.config.set("general.show_notifications", value=self.show_notifications_chk.IsChecked())


class PlaybackPanel(SettingsPanel):
    title = "Playback"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        sizer.Add(wx.StaticText(self, label="Sound Output Device:"), 0, wx.ALL, 5)
        from ..utils.audio_devices import list_audio_output_devices
        self._output_devices = list_audio_output_devices()
        device_names = ["System Default"] + [d["name"] for d in self._output_devices]
        self.output_device_combo = wx.ComboBox(self, choices=device_names, style=wx.CB_READONLY)
        set_accessible_name(self.output_device_combo, "Sound Output Device")
        saved_device = self.config.get("playback.output_device", default="")
        idx = device_names.index(saved_device) if saved_device in device_names else 0
        self.output_device_combo.SetSelection(idx)
        sizer.Add(self.output_device_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Default Volume:"), 0, wx.ALL, 5)
        self.volume_slider = wx.Slider(
            self, value=int(self.config.get("playback.volume", default=1.0) * 100),
            minValue=0, maxValue=100, style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        sizer.Add(self.volume_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Crossfade Duration (seconds):"), 0, wx.ALL, 5)
        self.crossfade_spin = wx.SpinCtrl(
            self, value=str(self.config.get("playback.crossfade_duration", default=0)),
            min=0, max=10,
        )
        sizer.Add(self.crossfade_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.gapless_chk = wx.CheckBox(self, label="Gapless playback")
        self.gapless_chk.SetValue(self.config.get("playback.gapless", default=False))
        sizer.Add(self.gapless_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="ReplayGain:"), 0, wx.ALL, 5)
        self.replaygain_combo = wx.ComboBox(
            self, choices=["None", "Album", "Track"], style=wx.CB_READONLY,
        )
        self.replaygain_combo.SetStringSelection(
            self.config.get("playback.replaygain", default="none").title()
        )
        sizer.Add(self.replaygain_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.normalize_chk = wx.CheckBox(self, label="Normalize audio (EBU R128)")
        self.normalize_chk.SetValue(self.config.get("playback.normalize_audio", default=False))
        sizer.Add(self.normalize_chk, 0, wx.ALL, 5)

        self.remember_pos_chk = wx.CheckBox(self, label="Remember playback position")
        self.remember_pos_chk.SetValue(self.config.get("playback.remember_position", default=True))
        sizer.Add(self.remember_pos_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="AcoustID API Key (for Track Identifier, Ctrl+I):"), 0, wx.ALL, 5)
        self.acoustid_key_txt = wx.TextCtrl(
            self, value=self.config.get("playback.acoustid_api_key", default=""),
        )
        set_accessible_name(self.acoustid_key_txt, "AcoustID API Key")
        sizer.Add(self.acoustid_key_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        key_link = wx.StaticText(self, label="Get a free key at acoustid.org/api-key")
        sizer.Add(key_link, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

    def onSave(self) -> None:
        selected = self.output_device_combo.GetStringSelection()
        device_name = "" if selected == "System Default" else selected
        self.config.set("playback.output_device", value=device_name)
        self.config.set("playback.volume", value=self.volume_slider.GetValue() / 100.0)
        self.config.set("playback.crossfade_duration", value=self.crossfade_spin.GetValue())
        self.config.set("playback.gapless", value=self.gapless_chk.IsChecked())
        self.config.set("playback.replaygain", value=self.replaygain_combo.GetStringSelection().lower())
        self.config.set("playback.normalize_audio", value=self.normalize_chk.IsChecked())
        self.config.set("playback.remember_position", value=self.remember_pos_chk.IsChecked())
        self.config.set("playback.acoustid_api_key", value=self.acoustid_key_txt.GetValue().strip())


class RadioPanel(SettingsPanel):
    title = "Radio"

    # Set by SettingsDialog after construction (not through __init__, so
    # every other category panel's constructor call stays unchanged) --
    # the actual StationUpdater and a callback to refresh the Radio tab's
    # tree once a manual update completes.
    station_updater = None
    on_station_update: Any = None

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        sizer.Add(wx.StaticText(self, label="Default Country:"), 0, wx.ALL, 5)
        self.country_combo = wx.ComboBox(self, choices=[
            "All", "United States", "United Kingdom", "Canada", "Australia",
            "Germany", "France", "Spain", "Italy",
        ], style=wx.CB_READONLY)
        current = self.config.get("radio.default_country", default="all")
        self.country_combo.SetStringSelection("All" if current == "all" else current.title())
        sizer.Add(self.country_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.show_duplicates_chk = wx.CheckBox(self, label="Show duplicate stations")
        self.show_duplicates_chk.SetValue(self.config.get("radio.show_duplicates", default=False))
        sizer.Add(self.show_duplicates_chk, 0, wx.ALL, 5)

        self.auto_reconnect_chk = wx.CheckBox(self, label="Auto-reconnect on stream loss")
        self.auto_reconnect_chk.SetValue(self.config.get("radio.auto_reconnect", default=True))
        sizer.Add(self.auto_reconnect_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="Reconnect attempts before giving up:"), 0, wx.ALL, 5)
        self.reconnect_attempts_spin = wx.SpinCtrl(
            self, value=str(self.config.get("radio.reconnect_max_attempts", default=5)),
            min=1, max=20,
        )
        sizer.Add(self.reconnect_attempts_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Interval between reconnect attempts (seconds):"), 0, wx.ALL, 5)
        self.reconnect_interval_spin = wx.SpinCtrl(
            self, value=str(int(self.config.get("radio.reconnect_interval", default=2))),
            min=1, max=30,
        )
        sizer.Add(self.reconnect_interval_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.auto_play_last_chk = wx.CheckBox(self, label="Automatically play the last station on launch")
        self.auto_play_last_chk.SetValue(self.config.get("radio.auto_play_last_station", default=False))
        sizer.Add(self.auto_play_last_chk, 0, wx.ALL, 5)

        from radiomaster.services.station_update_scheduler import FREQUENCIES, FREQUENCY_LABELS
        sizer.Add(wx.StaticText(self, label="Station list update frequency:"), 0, wx.ALL, 5)
        self.update_freq_choice = wx.Choice(self, choices=[FREQUENCY_LABELS[f] for f in FREQUENCIES])
        current_freq = self.config.get("radio.station_update_frequency", default="weekly")
        self.update_freq_choice.SetSelection(
            FREQUENCIES.index(current_freq) if current_freq in FREQUENCIES else FREQUENCIES.index("weekly"))
        set_accessible_name(self.update_freq_choice, "Station list update frequency")
        sizer.Add(self.update_freq_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.update_now_btn = wx.Button(self, label="Update &Now")
        set_accessible_name(self.update_now_btn, "Update station list now")
        self.update_now_btn.Bind(wx.EVT_BUTTON, self._on_update_now)
        sizer.Add(self.update_now_btn, 0, wx.ALL, 5)

        self.update_now_status = wx.StaticText(self, label="")
        sizer.Add(self.update_now_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

    def _on_update_now(self, event: wx.CommandEvent) -> None:
        if not self.station_updater:
            return
        from radiomaster.utils.wx_safe import call_after_safe
        self.update_now_btn.Disable()
        self.update_now_status.SetLabel("Updating station list...")

        def progress_cb(bytes_read: int, total) -> None:
            if total:
                percent = min(100, int(bytes_read * 100 / total))
                text = f"Updating station list... {percent}%"
            else:
                text = f"Updating station list... ({bytes_read // 1024} KB)"
            call_after_safe(self, self.update_now_status.SetLabel, text)

        def worker():
            result = self.station_updater.update_now(progress_cb=progress_cb)
            if result.ok:
                call_after_safe(self, self.update_now_status.SetLabel,
                                 f"Updated {result.changed} stations ({result.unchanged} unchanged).")
                if self.on_station_update:
                    call_after_safe(self, self.on_station_update)
            else:
                call_after_safe(self, self.update_now_status.SetLabel, f"Update failed: {result.error}")
            call_after_safe(self, self.update_now_btn.Enable)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def onSave(self) -> None:
        from radiomaster.services.station_update_scheduler import FREQUENCIES
        self.config.set("radio.default_country", value=self.country_combo.GetStringSelection().lower())
        self.config.set("radio.show_duplicates", value=self.show_duplicates_chk.IsChecked())
        self.config.set("radio.auto_reconnect", value=self.auto_reconnect_chk.IsChecked())
        self.config.set("radio.reconnect_max_attempts", value=self.reconnect_attempts_spin.GetValue())
        self.config.set("radio.reconnect_interval", value=float(self.reconnect_interval_spin.GetValue()))
        self.config.set("radio.auto_play_last_station", value=self.auto_play_last_chk.IsChecked())
        self.config.set("radio.station_update_frequency", value=FREQUENCIES[self.update_freq_choice.GetSelection()])


class PodcastsPanel(SettingsPanel):
    title = "Podcasts"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        from radiomaster.utils.paths import get_podcasts_dir
        sizer.Add(wx.StaticText(self, label="Podcast Download Location:"), 0, wx.ALL, 5)
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        # get_podcasts_dir(), not a raw config.get() -- same self-healing
        # reasoning as Downloads/Recordings above. Each podcast gets its
        # own subfolder under here (see podcast_panel.py's _on_download),
        # so this is a dedicated location, not the shared Downloads one.
        self.podcast_path_txt = wx.TextCtrl(self, value=get_podcasts_dir())
        path_sizer.Add(self.podcast_path_txt, 1, wx.EXPAND)
        podcast_browse_btn = wx.Button(self, label="Browse...")
        podcast_browse_btn.Bind(wx.EVT_BUTTON, lambda e: self._browse(self.podcast_path_txt))
        path_sizer.Add(podcast_browse_btn, 0, wx.LEFT, 5)
        sizer.Add(path_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.auto_download_chk = wx.CheckBox(self, label="Auto-download new episodes")
        self.auto_download_chk.SetValue(self.config.get("podcasts.auto_download", default=False))
        sizer.Add(self.auto_download_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="Episodes to download per podcast:"), 0, wx.ALL, 5)
        self.download_limit_spin = wx.SpinCtrl(
            self, value=str(self.config.get("podcasts.download_limit", default=3)),
            min=1, max=100,
        )
        sizer.Add(self.download_limit_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Episodes to keep:"), 0, wx.ALL, 5)
        self.keep_episodes_spin = wx.SpinCtrl(
            self, value=str(self.config.get("podcasts.keep_episodes", default=10)),
            min=1, max=1000,
        )
        sizer.Add(self.keep_episodes_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.sync_gpodder_chk = wx.CheckBox(self, label="Sync with gpodder.net")
        self.sync_gpodder_chk.SetValue(self.config.get("podcasts.sync_gpodder", default=False))
        sizer.Add(self.sync_gpodder_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="gPodder Username:"), 0, wx.ALL, 5)
        self.gpodder_user_txt = wx.TextCtrl(
            self, value=self.config.get("podcasts.gpodder_username", default=""),
        )
        sizer.Add(self.gpodder_user_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Podcast Index API Key (for a second search directory):"), 0, wx.ALL, 5)
        self.podcastindex_key_txt = wx.TextCtrl(
            self, value=self.config.get("podcasts.podcastindex_api_key", default=""),
        )
        set_accessible_name(self.podcastindex_key_txt, "Podcast Index API Key")
        sizer.Add(self.podcastindex_key_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Podcast Index API Secret:"), 0, wx.ALL, 5)
        self.podcastindex_secret_txt = wx.TextCtrl(
            self, value=self.config.get("podcasts.podcastindex_api_secret", default=""),
        )
        set_accessible_name(self.podcastindex_secret_txt, "Podcast Index API Secret")
        sizer.Add(self.podcastindex_secret_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        podcastindex_link = wx.StaticText(self, label="Get a free key at api.podcastindex.org")
        sizer.Add(podcastindex_link, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Episode order:"), 0, wx.ALL, 5)
        self.episode_order_choice = wx.ComboBox(
            self, choices=["Newest first", "Oldest first"], style=wx.CB_READONLY,
        )
        current_order = self.config.get("podcasts.episode_order", default="newest")
        self.episode_order_choice.SetStringSelection(
            "Oldest first" if current_order == "oldest" else "Newest first"
        )
        set_accessible_name(self.episode_order_choice, "Episode order")
        sizer.Add(self.episode_order_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.auto_advance_chk = wx.CheckBox(self, label="Auto-advance to the next episode when one finishes")
        self.auto_advance_chk.SetValue(self.config.get("podcasts.auto_advance", default=False))
        sizer.Add(self.auto_advance_chk, 0, wx.ALL, 5)

    def _browse(self, ctrl: wx.TextCtrl) -> None:
        dlg = wx.DirDialog(self, "Choose directory", ctrl.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def onSave(self) -> None:
        self.config.set("podcasts.download_path", value=self.podcast_path_txt.GetValue())
        self.config.set("podcasts.auto_download", value=self.auto_download_chk.IsChecked())
        self.config.set("podcasts.download_limit", value=self.download_limit_spin.GetValue())
        self.config.set("podcasts.keep_episodes", value=self.keep_episodes_spin.GetValue())
        self.config.set("podcasts.sync_gpodder", value=self.sync_gpodder_chk.IsChecked())
        self.config.set("podcasts.gpodder_username", value=self.gpodder_user_txt.GetValue().strip())
        self.config.set("podcasts.podcastindex_api_key", value=self.podcastindex_key_txt.GetValue().strip())
        self.config.set("podcasts.podcastindex_api_secret", value=self.podcastindex_secret_txt.GetValue().strip())
        self.config.set(
            "podcasts.episode_order",
            value="oldest" if self.episode_order_choice.GetStringSelection() == "Oldest first" else "newest",
        )
        self.config.set("podcasts.auto_advance", value=self.auto_advance_chk.IsChecked())


class DownloadsPanel(SettingsPanel):
    title = "Downloads"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        sizer.Add(wx.StaticText(self, label="Download Location:"), 0, wx.ALL, 5)
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        from radiomaster.utils.paths import get_downloads_dir
        # get_downloads_dir(), not a raw config.get() -- self-heals a
        # value saved once while running installed (or before being
        # moved to a portable location) back to the correct portable
        # default instead of showing that stale Music-folder path
        # forever after. See get_downloads_dir()'s own docstring.
        self.download_path_txt = wx.TextCtrl(self, value=get_downloads_dir())
        path_sizer.Add(self.download_path_txt, 1, wx.EXPAND)
        btn = wx.Button(self, label="Browse...")
        btn.Bind(wx.EVT_BUTTON, lambda e: self._browse(self.download_path_txt))
        path_sizer.Add(btn, 0, wx.LEFT, 5)
        sizer.Add(path_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Max Concurrent Downloads:"), 0, wx.ALL, 5)
        self.max_concurrent_spin = wx.SpinCtrl(
            self, value=str(self.config.get("downloads.max_concurrent", default=3)),
            min=1, max=10,
        )
        sizer.Add(self.max_concurrent_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Audio Format:"), 0, wx.ALL, 5)
        self.format_combo = wx.ComboBox(
            self, choices=["MP3", "AAC", "OGG", "FLAC", "WAV", "M4A"], style=wx.CB_READONLY,
        )
        self.format_combo.SetStringSelection(
            self.config.get("downloads.audio_format", default="mp3").upper()
        )
        sizer.Add(self.format_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Audio Quality:"), 0, wx.ALL, 5)
        self.quality_combo = wx.ComboBox(
            self, choices=["96k", "128k", "192k", "256k", "320k", "Best"], style=wx.CB_READONLY,
        )
        self.quality_combo.SetStringSelection(
            self.config.get("downloads.audio_quality", default="192k")
        )
        sizer.Add(self.quality_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.embed_metadata_chk = wx.CheckBox(self, label="Embed metadata (ID3 tags)")
        self.embed_metadata_chk.SetValue(self.config.get("downloads.embed_metadata", default=True))
        sizer.Add(self.embed_metadata_chk, 0, wx.ALL, 5)

        self.embed_artwork_chk = wx.CheckBox(self, label="Embed artwork")
        self.embed_artwork_chk.SetValue(self.config.get("downloads.embed_artwork", default=True))
        sizer.Add(self.embed_artwork_chk, 0, wx.ALL, 5)

    def _browse(self, ctrl: wx.TextCtrl) -> None:
        dlg = wx.DirDialog(self, "Choose directory", ctrl.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def onSave(self) -> None:
        self.config.set("downloads.download_path", value=self.download_path_txt.GetValue())
        self.config.set("downloads.max_concurrent", value=self.max_concurrent_spin.GetValue())
        self.config.set("downloads.audio_format", value=self.format_combo.GetStringSelection().lower())
        self.config.set("downloads.audio_quality", value=self.quality_combo.GetStringSelection())
        self.config.set("downloads.embed_metadata", value=self.embed_metadata_chk.IsChecked())
        self.config.set("downloads.embed_artwork", value=self.embed_artwork_chk.IsChecked())


class RecordingsPanel(SettingsPanel):
    title = "Recordings"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        sizer.Add(wx.StaticText(self, label="Recording Location:"), 0, wx.ALL, 5)
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        from radiomaster.utils.paths import get_recordings_dir
        # get_recordings_dir() -- same self-healing reasoning as the
        # Download Location field above; this is also what actually
        # decides where recordings get written (see radio_panel.py), so
        # showing anything else here would make Settings lie about it.
        self.recording_path_txt = wx.TextCtrl(self, value=get_recordings_dir())
        path_sizer.Add(self.recording_path_txt, 1, wx.EXPAND)
        btn = wx.Button(self, label="Browse...")
        btn.Bind(wx.EVT_BUTTON, lambda e: self._browse(self.recording_path_txt))
        path_sizer.Add(btn, 0, wx.LEFT, 5)
        sizer.Add(path_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.match_source_chk = wx.CheckBox(
            self, label="Record in the station's original format when possible "
                        "(codec/bitrate/sample rate/channels)")
        self.match_source_chk.SetValue(self.config.get("recordings.match_source_format", default=True))
        sizer.Add(self.match_source_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="Recording Format:"), 0, wx.ALL, 5)
        self.rec_format_combo = wx.ComboBox(
            self, choices=["MP3", "AAC", "OGG", "FLAC", "WAV"], style=wx.CB_READONLY,
        )
        self.rec_format_combo.SetStringSelection(
            self.config.get("recordings.recording_format", default="mp3").upper()
        )
        sizer.Add(self.rec_format_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Recording Quality:"), 0, wx.ALL, 5)
        self.rec_quality_combo = wx.ComboBox(
            self, choices=["128k", "192k", "256k", "320k", "Best"], style=wx.CB_READONLY,
        )
        self.rec_quality_combo.SetStringSelection(
            self.config.get("recordings.recording_quality", default="320k")
        )
        sizer.Add(self.rec_quality_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Format/Quality only apply when NOT matching the source (they're
        # ignored -- see RecordingSession.match_source -- while it's on),
        # so disable them together with the checkbox instead of leaving
        # two controls visibly enabled but silently inert, which a screen
        # reader user would have no way to discover.
        def _on_match_source_toggle(event: wx.CommandEvent) -> None:
            enabled = not self.match_source_chk.IsChecked()
            self.rec_format_combo.Enable(enabled)
            self.rec_quality_combo.Enable(enabled)
            event.Skip()

        self.match_source_chk.Bind(wx.EVT_CHECKBOX, _on_match_source_toggle)
        self.rec_format_combo.Enable(not self.match_source_chk.IsChecked())
        self.rec_quality_combo.Enable(not self.match_source_chk.IsChecked())

        self.split_tracks_chk = wx.CheckBox(self, label="Split recordings into tracks")
        self.split_tracks_chk.SetValue(self.config.get("recordings.split_tracks", default=True))
        sizer.Add(self.split_tracks_chk, 0, wx.ALL, 5)

        self.add_metadata_chk = wx.CheckBox(self, label="Add metadata to recordings")
        self.add_metadata_chk.SetValue(self.config.get("recordings.add_metadata", default=True))
        sizer.Add(self.add_metadata_chk, 0, wx.ALL, 5)

    def _browse(self, ctrl: wx.TextCtrl) -> None:
        dlg = wx.DirDialog(self, "Choose directory", ctrl.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def onSave(self) -> None:
        self.config.set("recordings.recording_path", value=self.recording_path_txt.GetValue())
        self.config.set("recordings.match_source_format", value=self.match_source_chk.IsChecked())
        self.config.set("recordings.recording_format", value=self.rec_format_combo.GetStringSelection().lower())
        self.config.set("recordings.recording_quality", value=self.rec_quality_combo.GetStringSelection())
        self.config.set("recordings.split_tracks", value=self.split_tracks_chk.IsChecked())
        self.config.set("recordings.add_metadata", value=self.add_metadata_chk.IsChecked())


class NetworkPanel(SettingsPanel):
    title = "Network"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        self.proxy_enabled_chk = wx.CheckBox(self, label="Use proxy server")
        self.proxy_enabled_chk.SetValue(self.config.get("network.proxy_enabled", default=False))
        sizer.Add(self.proxy_enabled_chk, 0, wx.ALL, 5)

        sizer.Add(wx.StaticText(self, label="Proxy Host:"), 0, wx.ALL, 5)
        self.proxy_host_txt = wx.TextCtrl(
            self, value=self.config.get("network.proxy_host", default=""),
        )
        sizer.Add(self.proxy_host_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Proxy Port:"), 0, wx.ALL, 5)
        self.proxy_port_spin = wx.SpinCtrl(
            self, value=str(self.config.get("network.proxy_port", default=8080)),
            min=1, max=65535,
        )
        sizer.Add(self.proxy_port_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="Connection Timeout (seconds):"), 0, wx.ALL, 5)
        self.timeout_spin = wx.SpinCtrl(
            self, value=str(self.config.get("network.timeout", default=30)),
            min=5, max=300,
        )
        sizer.Add(self.timeout_spin, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        sizer.Add(wx.StaticText(self, label="User Agent:"), 0, wx.ALL, 5)
        self.user_agent_txt = wx.TextCtrl(
            self, value=self.config.get("network.user_agent", default="RadioMaster+/5.33.20"),
        )
        sizer.Add(self.user_agent_txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

    def onSave(self) -> None:
        self.config.set("network.proxy_enabled", value=self.proxy_enabled_chk.IsChecked())
        self.config.set("network.proxy_host", value=self.proxy_host_txt.GetValue().strip())
        self.config.set("network.proxy_port", value=self.proxy_port_spin.GetValue())
        self.config.set("network.timeout", value=self.timeout_spin.GetValue())
        self.config.set("network.user_agent", value=self.user_agent_txt.GetValue())


class AccessibilityPanel(SettingsPanel):
    title = "Accessibility"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        self.high_contrast_chk = wx.CheckBox(self, label="High contrast mode")
        self.high_contrast_chk.SetValue(self.config.get("accessibility.high_contrast", default=False))
        sizer.Add(self.high_contrast_chk, 0, wx.ALL, 5)

        self.dyslexia_font_chk = wx.CheckBox(self, label="Use dyslexia-friendly font (OpenDyslexic)")
        self.dyslexia_font_chk.SetValue(self.config.get("accessibility.dyslexia_font", default=False))
        sizer.Add(self.dyslexia_font_chk, 0, wx.ALL, 5)

        self.screen_reader_chk = wx.CheckBox(self, label="Screen reader optimized mode")
        self.screen_reader_chk.SetValue(self.config.get("accessibility.screen_reader_optimized", default=True))
        sizer.Add(self.screen_reader_chk, 0, wx.ALL, 5)

        self.keyboard_nav_chk = wx.CheckBox(self, label="Enhanced keyboard navigation")
        self.keyboard_nav_chk.SetValue(self.config.get("accessibility.keyboard_navigation", default=True))
        sizer.Add(self.keyboard_nav_chk, 0, wx.ALL, 5)

        self.focus_indicators_chk = wx.CheckBox(self, label="Show focus indicators")
        self.focus_indicators_chk.SetValue(self.config.get("accessibility.focus_indicators", default=True))
        sizer.Add(self.focus_indicators_chk, 0, wx.ALL, 5)

        self.reduce_motion_chk = wx.CheckBox(self, label="Reduce motion and animations")
        self.reduce_motion_chk.SetValue(self.config.get("accessibility.reduce_motion", default=False))
        sizer.Add(self.reduce_motion_chk, 0, wx.ALL, 5)

        info = wx.StaticText(self, label="Changes to accessibility settings may require restarting the application.")
        info.Wrap(600)
        sizer.Add(info, 0, wx.ALL, 5)

    def onSave(self) -> None:
        self.config.set("accessibility.high_contrast", value=self.high_contrast_chk.IsChecked())
        self.config.set("accessibility.dyslexia_font", value=self.dyslexia_font_chk.IsChecked())
        self.config.set("accessibility.screen_reader_optimized", value=self.screen_reader_chk.IsChecked())
        self.config.set("accessibility.keyboard_navigation", value=self.keyboard_nav_chk.IsChecked())
        self.config.set("accessibility.focus_indicators", value=self.focus_indicators_chk.IsChecked())
        self.config.set("accessibility.reduce_motion", value=self.reduce_motion_chk.IsChecked())


class AdvancedPanel(SettingsPanel):
    title = "Advanced"

    def makeSettings(self, sizer: wx.BoxSizer) -> None:
        sizer.Add(wx.StaticText(self, label="Logging Level:"), 0, wx.ALL, 5)
        self._log_level_choices = ["Off", "Info", "Debug", "Input/Output"]
        self._log_level_values = ["off", "info", "debug", "io"]
        self.logging_combo = wx.ComboBox(self, choices=self._log_level_choices, style=wx.CB_READONLY)
        set_accessible_name(self.logging_combo, "Logging Level")
        current_level = self.config.get("logging.level", default="info")
        idx = self._log_level_values.index(current_level) if current_level in self._log_level_values else 1
        self.logging_combo.SetSelection(idx)
        sizer.Add(self.logging_combo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        log_info = wx.StaticText(
            self,
            label="Debug and Input/Output modes write a detailed log to the app's data "
                  "folder and may affect performance -- use Info for normal use.",
        )
        log_info.Wrap(600)
        sizer.Add(log_info, 0, wx.ALL, 5)

        log_path_info = wx.StaticText(self, label=f"Log file location: {get_paths()['logs']}")
        log_path_info.Wrap(600)
        sizer.Add(log_path_info, 0, wx.ALL, 5)

        # Auto-update the YouTube library (yt-dlp) in the background.
        self.ytdlp_auto_update_chk = wx.CheckBox(
            self, label="Automatically update the YouTube library (yt-dlp) in the background")
        self.ytdlp_auto_update_chk.SetValue(
            self.config.get("updates.ytdlp_auto_update", default=True))
        sizer.Add(self.ytdlp_auto_update_chk, 0, wx.ALL, 5)

        ytdlp_info = wx.StaticText(
            self,
            label="Checks for a newer yt-dlp on startup (at most weekly) and updates it "
                  "silently. Keeping it current is the best way to keep YouTube playback "
                  "working. You can always update manually via Help > Update YouTube Library.",
        )
        ytdlp_info.Wrap(600)
        sizer.Add(ytdlp_info, 0, wx.ALL, 5)

    def onSave(self) -> None:
        new_level = self._log_level_values[self.logging_combo.GetSelection()]
        if new_level != self.config.get("logging.level", default="info"):
            self.config.set("logging.level", value=new_level)
            from ..utils.logging_setup import setup_logging
            setup_logging(level=new_level, log_dir=get_paths()["logs"])
        self.config.set("updates.ytdlp_auto_update",
                        value=self.ytdlp_auto_update_chk.IsChecked())


# ---------------------------------------------------------------------------
# MultiCategorySettingsDialog  (analogous to NVDA's MultiCategorySettingsDialog)
# ---------------------------------------------------------------------------
class SettingsDialog(wx.Dialog):
    """Multi-category settings dialog with a list of categories on the left
    and a settings panel on the right, following NVDA's pattern.

    Category panels are defined in ``category_classes`` and are lazily
    instantiated when first selected.
    """

    title = "Settings"
    category_classes: list[Type[SettingsPanel]] = [
        GeneralPanel,
        PlaybackPanel,
        RadioPanel,
        PodcastsPanel,
        DownloadsPanel,
        RecordingsPanel,
        NetworkPanel,
        AccessibilityPanel,
        AdvancedPanel,
    ]

    def __init__(self, parent: wx.Window, config: Config,
                 station_updater: Any = None, on_station_update: Any = None) -> None:
        self.config = config
        # Only RadioPanel uses these (its "Update Now" button) -- passed
        # in here rather than through every panel class's __init__ so the
        # other 8 categories' constructors stay untouched; see _get_panel.
        self.station_updater = station_updater
        self.on_station_update = on_station_update
        self._panel_map: dict[int, SettingsPanel] = {}
        self._current_panel: SettingsPanel | None = None

        super().__init__(
            parent, title=self.title,
            size=(800, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX,
        )

        self._build_ui()
        self.Centre(wx.BOTH)

    def _build_ui(self) -> None:
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Content area: category list + settings panel ---
        content_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: category list
        cat_label = wx.StaticText(self, label="&Categories:")
        content_sizer.Add(cat_label, 0, wx.ALL, 5)

        self._cat_list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER,
            size=(160, 300),
        )
        self._cat_list.InsertColumn(0, "Categories")
        for cls in self.category_classes:
            self._cat_list.Append((cls.title,))
        content_sizer.Add(self._cat_list, 0, wx.EXPAND | wx.ALL, 5)

        # Right: container for settings panels
        self._container = wx.Panel(self, style=wx.TAB_TRAVERSAL | wx.BORDER_THEME)
        self._container_sizer = wx.BoxSizer(wx.VERTICAL)
        self._container.SetSizer(self._container_sizer)
        content_sizer.Add(self._container, 1, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(content_sizer, 1, wx.EXPAND)

        # --- Buttons ---
        btn_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL | wx.APPLY)
        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(main_sizer)

        # Select first category and set focus to the category list
        self._cat_list.Select(0)
        self._switch_to(0)
        # Use CallAfter to ensure focus lands on the category list after the
        # dialog is fully constructed and shown (wx.Dialog defaults to focusing
        # the button sizer, which we override here).
        wx.CallAfter(self._cat_list.SetFocus)

        # Bind events
        self._cat_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_category_change)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_BUTTON, self._on_apply, id=wx.ID_APPLY)
        self.Bind(wx.EVT_BUTTON, self._on_cancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _get_panel(self, index: int) -> SettingsPanel:
        if index not in self._panel_map:
            cls = self.category_classes[index]
            panel = cls(self._container, self.config)
            if isinstance(panel, RadioPanel):
                panel.station_updater = self.station_updater
                panel.on_station_update = self.on_station_update
            panel.Hide()
            self._container_sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 4)
            self._panel_map[index] = panel
        return self._panel_map[index]

    def _switch_to(self, index: int) -> None:
        if self._current_panel:
            self._current_panel.onPanelDeactivated()
        panel = self._get_panel(index)
        panel.onPanelActivated()
        self._current_panel = panel
        self._container.Layout()

    def _on_category_change(self, evt: wx.ListEvent) -> None:
        self._switch_to(evt.GetIndex())

    def _on_char_hook(self, evt: wx.KeyEvent) -> None:
        if evt.ControlDown() and evt.GetKeyCode() == wx.WXK_TAB:
            idx = self._cat_list.GetFirstSelected()
            count = self._cat_list.GetItemCount()
            new_idx = (idx - 1) if evt.ShiftDown() else (idx + 1)
            new_idx %= count
            self._cat_list.Select(new_idx)
            self._switch_to(new_idx)
            self._cat_list.SetFocus()
        else:
            evt.Skip()

    def _save_all(self) -> None:
        for panel in self._panel_map.values():
            panel.onSave()
        self.config.save()

    def _on_ok(self, evt: wx.CommandEvent) -> None:
        self._save_all()
        self.EndModal(wx.ID_OK)

    def _on_apply(self, evt: wx.CommandEvent) -> None:
        self._save_all()
        wx.MessageBox("Settings applied successfully.", "Settings", wx.OK | wx.ICON_INFORMATION, self)

    def _on_cancel(self, evt: wx.CommandEvent) -> None:
        for panel in self._panel_map.values():
            panel.onDiscard()
        self.EndModal(wx.ID_CANCEL)
