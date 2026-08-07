"""Keyboard shortcut editor dialog for RadioMaster+."""

import wx
from typing import Any


DEFAULT_SHORTCUTS: dict[str, dict[str, str]] = {
    "play_pause": {"primary": "Ctrl+P", "secondary": "Space", "description": "Play / Pause"},
    "stop": {"primary": "Ctrl+S", "secondary": "", "description": "Stop playback"},
    "next_track": {"primary": "Ctrl+Right", "secondary": "", "description": "Next track"},
    "prev_track": {"primary": "Ctrl+Left", "secondary": "", "description": "Previous track"},
    "first_track": {"primary": "Ctrl+Shift+Left", "secondary": "", "description": "First track"},
    "last_track": {"primary": "Ctrl+Shift+Right", "secondary": "", "description": "Last track"},
    "seek_forward": {"primary": "Right", "secondary": "", "description": "Seek forward"},
    "seek_backward": {"primary": "Left", "secondary": "", "description": "Seek backward"},
    "volume_up": {"primary": "Ctrl+Up", "secondary": "", "description": "Volume up"},
    "volume_down": {"primary": "Ctrl+Down", "secondary": "", "description": "Volume down"},
    "effects_menu": {"primary": "Ctrl+E", "secondary": "", "description": "Open effects menu"},
    "open_file": {"primary": "Ctrl+O", "secondary": "", "description": "Open file"},
    "open_url": {"primary": "Ctrl+U", "secondary": "", "description": "Open URL"},
    "settings": {"primary": "Ctrl+,", "secondary": "", "description": "Open settings"},
    "fullscreen": {"primary": "F11", "secondary": "", "description": "Toggle fullscreen"},
    "toggle_sidebar": {"primary": "Ctrl+B", "secondary": "", "description": "Toggle sidebar"},
    "toggle_lyrics": {"primary": "Ctrl+L", "secondary": "", "description": "Toggle lyrics panel"},
    "download_manager": {"primary": "Ctrl+D", "secondary": "", "description": "Open download manager"},
    "scheduler": {"primary": "Ctrl+R", "secondary": "", "description": "Open scheduler"},
    "track_identifier": {"primary": "Ctrl+I", "secondary": "", "description": "Open track identifier"},
    "shortcut_editor": {"primary": "Ctrl+K", "secondary": "", "description": "Open shortcut editor"},
    "search": {"primary": "Ctrl+F", "secondary": "", "description": "Search"},
    "quit": {"primary": "Alt+F4", "secondary": "", "description": "Quit application"},
}


class ShortcutEditor(wx.Dialog):
    """Dialog for viewing and editing keyboard shortcuts."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="Keyboard Shortcuts", size=(600, 500))
        self._shortcuts: dict[str, dict[str, str]] = dict(DEFAULT_SHORTCUTS)
        self._setup_ui()
        self._load_shortcuts()
        self.Centre()

    def _setup_ui(self) -> None:
        """Create the shortcut editor layout."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Shortcut list
        self._shortcut_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._shortcut_list.SetName("Keyboard Shortcuts")
        self._shortcut_list.AppendColumn("Action", width=200)
        self._shortcut_list.AppendColumn("Primary Key", width=150)
        self._shortcut_list.AppendColumn("Secondary Key", width=150)
        main_sizer.Add(self._shortcut_list, 1, wx.EXPAND | wx.ALL, 8)

        # Edit controls
        edit_sizer = wx.BoxSizer(wx.HORIZONTAL)

        edit_sizer.Add(wx.StaticText(self, label="Primary:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._primary_text = wx.TextCtrl(self, size=(120, -1))
        self._primary_text.SetName("Primary Shortcut")
        edit_sizer.Add(self._primary_text, 0, wx.LEFT | wx.RIGHT, 4)

        edit_sizer.Add(wx.StaticText(self, label="Secondary:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._secondary_text = wx.TextCtrl(self, size=(120, -1))
        self._secondary_text.SetName("Secondary Shortcut")
        edit_sizer.Add(self._secondary_text, 0, wx.LEFT | wx.RIGHT, 4)

        self._btn_set = wx.Button(self, label="Set")
        self._btn_set.SetName("Set Shortcut")
        edit_sizer.Add(self._btn_set, 0, wx.RIGHT, 4)

        self._btn_clear = wx.Button(self, label="Clear")
        self._btn_clear.SetName("Clear Shortcut")
        edit_sizer.Add(self._btn_clear, 0)

        main_sizer.Add(edit_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_reset = wx.Button(self, label="Reset to Defaults")
        btn_sizer.Add(self._btn_reset, 0, wx.RIGHT, 8)
        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(wx.Button(self, wx.ID_OK, "Close"))

        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(main_sizer)

        # Bind events
        self._shortcut_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self._btn_set.Bind(wx.EVT_BUTTON, self._on_set)
        self._btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        self._btn_reset.Bind(wx.EVT_BUTTON, self._on_reset)

    def _load_shortcuts(self) -> None:
        """Load shortcuts into the list."""
        self._shortcut_list.DeleteAllItems()
        for action, data in self._shortcuts.items():
            idx = self._shortcut_list.AppendItem(data.get("description", action))
            self._shortcut_list.SetItem(idx, 1, data.get("primary", ""))
            self._shortcut_list.SetItem(idx, 2, data.get("secondary", ""))

    def _on_select(self, event: wx.ListEvent) -> None:
        """Handle shortcut selection."""
        idx = event.GetIndex()
        if idx >= 0:
            action = self._shortcut_list.GetItemText(idx)
            for key, data in self._shortcuts.items():
                if data.get("description") == action or key == action:
                    self._current_action = key
                    self._primary_text.SetValue(data.get("primary", ""))
                    self._secondary_text.SetValue(data.get("secondary", ""))
                    break

    def _on_set(self, event: wx.CommandEvent) -> None:
        """Set the shortcut for the selected action."""
        if hasattr(self, "_current_action") and self._current_action:
            primary = self._primary_text.GetValue().strip()
            secondary = self._secondary_text.GetValue().strip()
            if primary:
                self._shortcuts[self._current_action]["primary"] = primary
                self._shortcuts[self._current_action]["secondary"] = secondary
                self._load_shortcuts()

    def _on_clear(self, event: wx.CommandEvent) -> None:
        """Clear the shortcut for the selected action."""
        if hasattr(self, "_current_action") and self._current_action:
            self._shortcuts[self._current_action]["primary"] = ""
            self._shortcuts[self._current_action]["secondary"] = ""
            self._primary_text.SetValue("")
            self._secondary_text.SetValue("")
            self._load_shortcuts()

    def _on_reset(self, event: wx.CommandEvent) -> None:
        """Reset all shortcuts to defaults."""
        dlg = wx.MessageDialog(self, "Reset all keyboard shortcuts to defaults?",
                               "Confirm", wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self._shortcuts = dict(DEFAULT_SHORTCUTS)
            self._load_shortcuts()
        dlg.Destroy()
