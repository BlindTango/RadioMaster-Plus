"""Settings dialog for RadioMaster+."""

import wx
from typing import Any
from radiomaster.utils.config import ConfigManager


class SettingsDialog(wx.Dialog):
    """Application settings dialog with categorized settings."""

    def __init__(self, parent: wx.Window, config: ConfigManager) -> None:
        super().__init__(parent, title="Settings", size=(600, 500))
        self._config = config
        self._setup_ui()
        self._load_settings()
        self.Centre()

    def _setup_ui(self) -> None:
        """Create the settings dialog layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Notebook for categories
        self._notebook = wx.Notebook(self)

        # General page
        self._general_panel = self._create_general_page()
        self._notebook.AddPage(self._general_panel, "General")

        # Playback page
        self._playback_panel = self._create_playback_page()
        self._notebook.AddPage(self._playback_panel, "Playback")

        # Radio page
        self._radio_panel = self._create_radio_page()
        self._notebook.AddPage(self._radio_panel, "Radio")

        # Downloads page
        self._downloads_panel = self._create_downloads_page()
        self._notebook.AddPage(self._downloads_panel, "Downloads")

        # Recordings page
        self._recordings_panel = self._create_recordings_page()
        self._notebook.AddPage(self._recordings_panel, "Recordings")

        # Network page
        self._network_panel = self._create_network_page()
        self._notebook.AddPage(self._network_panel, "Network")

        # Audio page
        self._audio_panel = self._create_audio_page()
        self._notebook.AddPage(self._audio_panel, "Audio")

        # Accessibility page
        self._accessibility_panel = self._create_accessibility_page()
        self._notebook.AddPage(self._accessibility_panel, "Accessibility")

        main_sizer.Add(self._notebook, 1, wx.EXPAND | wx.ALL, 8)

        # Buttons
        btn_sizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        main_sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        self.SetSizer(main_sizer)

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _create_general_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Language
        lang_sizer = wx.BoxSizer(wx.HORIZONTAL)
        lang_sizer.Add(wx.StaticText(panel, label="Language:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._lang_choice = wx.Choice(panel, choices=["English"])
        self._lang_choice.SetName("Language")
        lang_sizer.Add(self._lang_choice, 0, wx.LEFT, 8)
        sizer.Add(lang_sizer, 0, wx.ALL, 8)

        # Startup behavior
        sizer.Add(wx.StaticText(panel, label="Startup behavior:"), 0, wx.LEFT | wx.TOP, 8)
        self._startup_choice = wx.Choice(panel, choices=["Normal", "Minimized", "Minimized to tray"])
        self._startup_choice.SetName("Startup Behavior")
        sizer.Add(self._startup_choice, 0, wx.LEFT | wx.BOTTOM, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _create_playback_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Default volume
        vol_sizer = wx.BoxSizer(wx.HORIZONTAL)
        vol_sizer.Add(wx.StaticText(panel, label="Default volume:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._volume_spin = wx.SpinCtrl(panel, min=0, max=100, initial=80)
        self._volume_spin.SetName("Default Volume")
        vol_sizer.Add(self._volume_spin, 0, wx.LEFT, 8)
        sizer.Add(vol_sizer, 0, wx.ALL, 8)

        # Crossfade
        cf_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cf_sizer.Add(wx.StaticText(panel, label="Crossfade duration (s):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._crossfade_spin = wx.SpinCtrl(panel, min=0, max=30, initial=3)
        self._crossfade_spin.SetName("Crossfade Duration")
        cf_sizer.Add(self._crossfade_spin, 0, wx.LEFT, 8)
        sizer.Add(cf_sizer, 0, wx.ALL, 8)

        # Fade in/out
        fi_sizer = wx.BoxSizer(wx.HORIZONTAL)
        fi_sizer.Add(wx.StaticText(panel, label="Fade in (s):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._fadein_spin = wx.SpinCtrl(panel, min=0, max=10, initial=0)
        fi_sizer.Add(self._fadein_spin, 0, wx.LEFT, 8)
        fi_sizer.Add(wx.StaticText(panel, label="  Fade out (s):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 16)
        self._fadeout_spin = wx.SpinCtrl(panel, min=0, max=10, initial=0)
        fi_sizer.Add(self._fadeout_spin, 0, wx.LEFT, 8)
        sizer.Add(fi_sizer, 0, wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _create_radio_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._auto_sync = wx.CheckBox(panel, label="Auto-sync stations on startup")
        self._auto_sync.SetName("Auto Sync")
        sizer.Add(self._auto_sync, 0, wx.ALL, 8)

        sync_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sync_sizer.Add(wx.StaticText(panel, label="Sync interval (hours):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._sync_interval = wx.SpinCtrl(panel, min=1, max=168, initial=24)
        self._sync_interval.SetName("Sync Interval")
        sync_sizer.Add(self._sync_interval, 0, wx.LEFT, 8)
        sizer.Add(sync_sizer, 0, wx.ALL, 8)

        to_sizer = wx.BoxSizer(wx.HORIZONTAL)
        to_sizer.Add(wx.StaticText(panel, label="Connection timeout (s):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._timeout_spin = wx.SpinCtrl(panel, min=1, max=60, initial=10)
        self._timeout_spin.SetName("Connection Timeout")
        to_sizer.Add(self._timeout_spin, 0, wx.LEFT, 8)
        sizer.Add(to_sizer, 0, wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _create_downloads_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Download folder
        folder_sizer = wx.BoxSizer(wx.HORIZONTAL)
        folder_sizer.Add(wx.StaticText(panel, label="Download folder:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._download_folder = wx.TextCtrl(panel, size=(300, -1))
        self._download_folder.SetName("Download Folder")
        folder_sizer.Add(self._download_folder, 1, wx.LEFT, 8)
        self._btn_browse = wx.Button(panel, label="Browse...")
        folder_sizer.Add(self._btn_browse, 0, wx.LEFT, 4)
        sizer.Add(folder_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Concurrent downloads
        conc_sizer = wx.BoxSizer(wx.HORIZONTAL)
        conc_sizer.Add(wx.StaticText(panel, label="Max concurrent downloads:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._concurrent_spin = wx.SpinCtrl(panel, min=1, max=10, initial=3)
        self._concurrent_spin.SetName("Concurrent Downloads")
        conc_sizer.Add(self._concurrent_spin, 0, wx.LEFT, 8)
        sizer.Add(conc_sizer, 0, wx.ALL, 8)

        self._auto_dl = wx.CheckBox(panel, label="Auto-download new podcast episodes")
        sizer.Add(self._auto_dl, 0, wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        self._btn_browse.Bind(wx.EVT_BUTTON, self._on_browse_download)
        return panel

    def _create_recordings_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        folder_sizer = wx.BoxSizer(wx.HORIZONTAL)
        folder_sizer.Add(wx.StaticText(panel, label="Recordings folder:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._rec_folder = wx.TextCtrl(panel, size=(300, -1))
        self._rec_folder.SetName("Recordings Folder")
        folder_sizer.Add(self._rec_folder, 1, wx.LEFT, 8)
        self._btn_rec_browse = wx.Button(panel, label="Browse...")
        folder_sizer.Add(self._btn_rec_browse, 0, wx.LEFT, 4)
        sizer.Add(folder_sizer, 0, wx.EXPAND | wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        self._btn_rec_browse.Bind(wx.EVT_BUTTON, self._on_browse_rec)
        return panel

    def _create_network_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        proxy_sizer = wx.BoxSizer(wx.HORIZONTAL)
        proxy_sizer.Add(wx.StaticText(panel, label="Proxy URL:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._proxy_text = wx.TextCtrl(panel, size=(300, -1))
        self._proxy_text.SetName("Proxy URL")
        proxy_sizer.Add(self._proxy_text, 1, wx.LEFT, 8)
        sizer.Add(proxy_sizer, 0, wx.EXPAND | wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _create_audio_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sr_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sr_sizer.Add(wx.StaticText(panel, label="Sample rate:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._sample_rate = wx.Choice(panel, choices=["44100", "48000", "96000"])
        self._sample_rate.SetName("Sample Rate")
        sr_sizer.Add(self._sample_rate, 0, wx.LEFT, 8)
        sizer.Add(sr_sizer, 0, wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _create_accessibility_page(self) -> wx.Panel:
        panel = wx.Panel(self._notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Font size
        fs_sizer = wx.BoxSizer(wx.HORIZONTAL)
        fs_sizer.Add(wx.StaticText(panel, label="Font size:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._font_size = wx.SpinCtrl(panel, min=8, max=48, initial=12)
        self._font_size.SetName("Font Size")
        fs_sizer.Add(self._font_size, 0, wx.LEFT, 8)
        sizer.Add(fs_sizer, 0, wx.ALL, 8)

        # Dyslexia font
        self._dyslexia_font = wx.CheckBox(panel, label="Use dyslexia-friendly font (OpenDyslexic)")
        sizer.Add(self._dyslexia_font, 0, wx.ALL, 8)

        # SAPI mode
        sapi_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sapi_sizer.Add(wx.StaticText(panel, label="SAPI / Screen reader mode:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._sapi_mode = wx.Choice(panel, choices=["Coexist (SAPI for book, SR for UI)", "SAPI takes over", "Screen reader only"])
        self._sapi_mode.SetName("SAPI Mode")
        sapi_sizer.Add(self._sapi_mode, 0, wx.LEFT, 8)
        sizer.Add(sapi_sizer, 0, wx.ALL, 8)

        sizer.AddStretchSpacer()
        panel.SetSizer(sizer)
        return panel

    def _load_settings(self) -> None:
        """Load current settings into the dialog controls."""
        self._volume_spin.SetValue(int(self._config.get("playback", "default_volume", default=0.8) * 100))
        self._crossfade_spin.SetValue(self._config.get("playback", "crossfade_duration", default=3))
        self._fadein_spin.SetValue(self._config.get("playback", "fade_in_duration", default=0))
        self._fadeout_spin.SetValue(self._config.get("playback", "fade_out_duration", default=0))
        self._auto_sync.SetValue(self._config.get("radio", "auto_sync_on_startup", default=True))
        self._sync_interval.SetValue(self._config.get("radio", "sync_interval_hours", default=24))
        self._timeout_spin.SetValue(self._config.get("radio", "connection_timeout", default=10))
        self._concurrent_spin.SetValue(self._config.get("downloads", "max_concurrent", default=3))
        self._auto_dl.SetValue(self._config.get("downloads", "auto_download_podcasts", default=False))
        self._font_size.SetValue(self._config.get("accessibility", "font_size", default=12))
        self._dyslexia_font.SetValue(self._config.get("accessibility", "dyslexia_font", default=False))

    def _on_ok(self, event: wx.CommandEvent) -> None:
        """Save settings and close."""
        self._config.set("playback", "default_volume", value=self._volume_spin.GetValue() / 100.0)
        self._config.set("playback", "crossfade_duration", value=self._crossfade_spin.GetValue())
        self._config.set("playback", "fade_in_duration", value=self._fadein_spin.GetValue())
        self._config.set("playback", "fade_out_duration", value=self._fadeout_spin.GetValue())
        self._config.set("radio", "auto_sync_on_startup", value=self._auto_sync.GetValue())
        self._config.set("radio", "sync_interval_hours", value=self._sync_interval.GetValue())
        self._config.set("radio", "connection_timeout", value=self._timeout_spin.GetValue())
        self._config.set("downloads", "max_concurrent", value=self._concurrent_spin.GetValue())
        self._config.set("downloads", "auto_download_podcasts", value=self._auto_dl.GetValue())
        self._config.set("accessibility", "font_size", value=self._font_size.GetValue())
        self._config.set("accessibility", "dyslexia_font", value=self._dyslexia_font.GetValue())
        self._config.save()
        event.Skip()

    def _on_browse_download(self, event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(self, "Select download folder")
        if dlg.ShowModal() == wx.ID_OK:
            self._download_folder.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_browse_rec(self, event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(self, "Select recordings folder")
        if dlg.ShowModal() == wx.ID_OK:
            self._rec_folder.SetValue(dlg.GetPath())
        dlg.Destroy()
