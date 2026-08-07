"""Theme editor dialog with live preview for RadioMaster+."""

import wx
import json
from typing import Any
from radiomaster.ui.theme_manager import ThemeManager
from radiomaster.utils.accessibility import set_accessible_name


class ThemeEditorDialog(wx.Dialog):
    """Dialog for creating and editing themes with live preview."""

    THEME_KEYS = [
        ("bg_primary", "Background Primary"),
        ("bg_secondary", "Background Secondary"),
        ("bg_tertiary", "Background Tertiary"),
        ("text_primary", "Text Primary"),
        ("text_secondary", "Text Secondary"),
        ("accent", "Accent"),
        ("accent_hover", "Accent Hover"),
        ("highlight", "Highlight"),
        ("highlight_text", "Highlight Text"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("border", "Border"),
        ("control_face", "Control Face"),
        ("control_text", "Control Text"),
    ]

    def __init__(self, parent: wx.Window, theme_manager: ThemeManager) -> None:
        super().__init__(parent, title="Theme Editor", size=(700, 600))
        self._theme_manager = theme_manager
        self._current_colors: dict[str, str] = {}
        self._setup_ui()
        self._load_current_theme()
        self.Centre()

    def _setup_ui(self) -> None:
        """Create the theme editor layout."""
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: Color list
        left_panel = wx.Panel(self)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        left_sizer.Add(wx.StaticText(left_panel, label="Theme Colors"), 0, wx.ALL, 4)

        self._color_list = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self._color_list, "Theme Colors")
        self._color_list.AppendColumn("Property", width=150)
        self._color_list.AppendColumn("Value", width=100)
        left_sizer.Add(self._color_list, 1, wx.EXPAND | wx.ALL, 4)

        # Color picker
        picker_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._color_picker = wx.ColourPickerCtrl(left_panel)
        set_accessible_name(self._color_picker, "Color Picker")
        picker_sizer.Add(self._color_picker, 0, wx.RIGHT, 4)

        self._btn_apply = wx.Button(left_panel, label="Apply")
        set_accessible_name(self._btn_apply, "Apply Color")
        picker_sizer.Add(self._btn_apply, 0)

        left_sizer.Add(picker_sizer, 0, wx.ALL, 4)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_save = wx.Button(left_panel, label="Save Theme...")
        set_accessible_name(self._btn_save, "Save Theme")
        btn_sizer.Add(self._btn_save, 0, wx.RIGHT, 4)

        self._btn_load = wx.Button(left_panel, label="Load Theme...")
        set_accessible_name(self._btn_load, "Load Theme")
        btn_sizer.Add(self._btn_load, 0, wx.RIGHT, 4)

        self._btn_reset = wx.Button(left_panel, label="Reset")
        set_accessible_name(self._btn_reset, "Reset Theme")
        btn_sizer.Add(self._btn_reset, 0)

        left_sizer.Add(btn_sizer, 0, wx.ALL, 4)

        left_panel.SetSizer(left_sizer)
        main_sizer.Add(left_panel, 1, wx.EXPAND | wx.ALL, 4)

        # Right: Live preview
        right_panel = wx.Panel(self)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        right_sizer.Add(wx.StaticText(right_panel, label="Live Preview"), 0, wx.ALL, 4)

        self._preview = wx.Panel(right_panel, size=(250, 200))
        set_accessible_name(self._preview, "Theme Preview")
        right_sizer.Add(self._preview, 1, wx.EXPAND | wx.ALL, 4)

        # Preview elements
        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        self._preview_title = wx.StaticText(self._preview, label="Sample Text")
        preview_sizer.Add(self._preview_title, 0, wx.ALL, 8)

        self._preview_accent = wx.Button(self._preview, label="Button")
        preview_sizer.Add(self._preview_accent, 0, wx.ALL, 8)

        self._preview_highlight = wx.TextCtrl(self._preview, value="Highlighted text",
                                               style=wx.TE_READONLY)
        preview_sizer.Add(self._preview_highlight, 0, wx.ALL, 8)

        self._preview.SetSizer(preview_sizer)

        right_panel.SetSizer(right_sizer)
        main_sizer.Add(right_panel, 0, wx.EXPAND | wx.ALL, 4)

        # Close button
        close_sizer = wx.BoxSizer(wx.VERTICAL)
        close_sizer.Add(main_sizer, 1, wx.EXPAND)
        close_sizer.Add(wx.Button(self, wx.ID_CLOSE, "Close"), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(close_sizer)

        # Bind events
        self._color_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_color_select)
        self._btn_apply.Bind(wx.EVT_BUTTON, self._on_apply)
        self._btn_save.Bind(wx.EVT_BUTTON, self._on_save)
        self._btn_load.Bind(wx.EVT_BUTTON, self._on_load)
        self._btn_reset.Bind(wx.EVT_BUTTON, self._on_reset)
        self.Bind(wx.EVT_BUTTON, lambda e: self.Close(), id=wx.ID_CLOSE)
        # wx.ID_CLOSE (unlike wx.ID_CANCEL) doesn't get automatic
        # Escape-closes-dialog behavior, so bind it explicitly.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _load_current_theme(self) -> None:
        """Load the current theme colors into the editor."""
        self._color_list.DeleteAllItems()
        for key, label in self.THEME_KEYS:
            color = self._theme_manager.get_color(key)
            self._current_colors[key] = color
            idx = self._color_list.InsertItem(self._color_list.GetItemCount(), label)
            self._color_list.SetItem(idx, 1, color)

    def _on_color_select(self, event: wx.ListEvent) -> None:
        """Handle color selection from the list."""
        idx = event.GetIndex()
        if idx >= 0:
            color_str = self._color_list.GetItemText(idx, 1)
            try:
                color = wx.Colour()
                color.Set(color_str)
                self._color_picker.SetColour(color)
            except Exception:
                pass

    def _on_apply(self, event: wx.CommandEvent) -> None:
        """Apply the selected color."""
        idx = self._color_list.GetFirstSelected()
        if idx >= 0:
            key = self.THEME_KEYS[idx][0]
            color = self._color_picker.GetColour()
            hex_color = f"#{color.GetRed():02X}{color.GetGreen():02X}{color.GetBlue():02X}"
            self._current_colors[key] = hex_color
            self._color_list.SetItem(idx, 1, hex_color)
            self._update_preview()

    def _on_save(self, event: wx.CommandEvent) -> None:
        """Save the current theme."""
        dlg = wx.TextEntryDialog(self, "Enter theme name:", "Save Theme")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                theme_data = {"name": name, **self._current_colors}
                self._theme_manager.save_custom_theme(name, theme_data)
                self._theme_manager.apply_theme(name)
                wx.MessageBox(f"Theme '{name}' saved and applied.", "Success", wx.OK | wx.ICON_INFORMATION)
        dlg.Destroy()

    def _on_load(self, event: wx.CommandEvent) -> None:
        """Load a theme from file."""
        dlg = wx.FileDialog(self, "Load Theme", wildcard="JSON files (*.json)|*.json",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            try:
                with open(dlg.GetPath(), "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key in self._current_colors:
                    if key in data:
                        self._current_colors[key] = data[key]
                self._load_current_theme()
                self._update_preview()
            except Exception as e:
                wx.MessageBox(f"Failed to load theme: {e}", "Error", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()

    def _on_reset(self, event: wx.CommandEvent) -> None:
        """Reset to default theme."""
        self._load_current_theme()
        self._update_preview()

    def _update_preview(self) -> None:
        """Update the live preview panel."""
        colors = self._current_colors
        self._preview.SetBackgroundColour(wx.Colour(colors.get("bg_primary", "#FFFFFF")))
        self._preview_title.SetForegroundColour(wx.Colour(colors.get("text_primary", "#000000")))
        self._preview_accent.SetBackgroundColour(wx.Colour(colors.get("accent", "#0078D4")))
        self._preview_accent.SetForegroundColour(wx.Colour(colors.get("control_text", "#000000")))
        self._preview_highlight.SetBackgroundColour(wx.Colour(colors.get("highlight", "#FFFF00")))
        self._preview_highlight.SetForegroundColour(wx.Colour(colors.get("highlight_text", "#000000")))
        self._preview.Refresh()
