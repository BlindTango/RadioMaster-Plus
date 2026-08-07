"""Keyboard shortcut editor for RadioMaster+ with conflict detection."""

import wx
from typing import Dict, List, Tuple, Optional, Set
import json

from radiomaster.utils.config import ConfigManager


# Default keyboard shortcuts
DEFAULT_SHORTCUTS = {
    # Playback controls
    # play_pause/stop deliberately default to a modifier combo, not a bare
    # key: a bare Space/S accelerator applied globally steals those
    # keystrokes from every text box and list in the app (search boxes,
    # station names, custom station dialogs...) before they can be typed.
    # See main_window.py's _setup_accelerators() for the same reasoning.
    'play_pause': {'key': 'P', 'modifiers': ['Ctrl'], 'description': 'Play/Pause'},
    'stop': {'key': 'S', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Stop'},
    'volume_up': {'key': 'Up', 'modifiers': ['Ctrl'], 'description': 'Volume Up'},
    'volume_down': {'key': 'Down', 'modifiers': ['Ctrl'], 'description': 'Volume Down'},
    'mute': {'key': 'M', 'modifiers': ['Ctrl'], 'description': 'Mute'},
    'seek_forward': {'key': 'Right', 'modifiers': ['Ctrl'], 'description': 'Seek Forward 10s'},
    'seek_backward': {'key': 'Left', 'modifiers': ['Ctrl'], 'description': 'Seek Backward 10s'},
    
    # Navigation
    'next_track': {'key': 'N', 'modifiers': ['Ctrl'], 'description': 'Next Track'},
    'previous_track': {'key': 'P', 'modifiers': ['Ctrl'], 'description': 'Previous Track'},
    'next_tab': {'key': 'Tab', 'modifiers': ['Ctrl'], 'description': 'Next Tab'},
    'previous_tab': {'key': 'Tab', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Previous Tab'},
    
    # Search
    'search': {'key': 'F', 'modifiers': ['Ctrl'], 'description': 'Search'},
    'search_radio': {'key': 'F', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Search Radio'},
    'search_podcast': {'key': 'F', 'modifiers': ['Alt'], 'description': 'Search Podcasts'},
    
    # Library
    'add_station': {'key': 'A', 'modifiers': ['Ctrl'], 'description': 'Add Station'},
    'add_podcast': {'key': 'A', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Add Podcast'},
    'add_to_playlist': {'key': 'L', 'modifiers': ['Ctrl'], 'description': 'Add to Playlist'},
    'create_playlist': {'key': 'N', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Create Playlist'},
    
    # Bookmarks
    'add_bookmark': {'key': 'B', 'modifiers': ['Ctrl'], 'description': 'Add Bookmark'},
    'next_bookmark': {'key': 'B', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Next Bookmark'},
    'previous_bookmark': {'key': 'B', 'modifiers': ['Ctrl', 'Alt'], 'description': 'Previous Bookmark'},
    
    # Recording
    'start_recording': {'key': 'R', 'modifiers': ['Ctrl'], 'description': 'Start Recording'},
    'stop_recording': {'key': 'R', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Stop Recording'},
    
    # Sleep timer
    'toggle_sleep_timer': {'key': 'T', 'modifiers': ['Ctrl'], 'description': 'Toggle Sleep Timer'},
    
    # Effects
    'toggle_equalizer': {'key': 'E', 'modifiers': ['Ctrl'], 'description': 'Toggle Equalizer'},
    'toggle_effects': {'key': 'E', 'modifiers': ['Ctrl', 'Shift'], 'description': 'Toggle Effects Panel'},
    
    # View
    'toggle_fullscreen': {'key': 'F11', 'modifiers': [], 'description': 'Toggle Fullscreen'},
    'zoom_in': {'key': '+', 'modifiers': ['Ctrl'], 'description': 'Zoom In'},
    'zoom_out': {'key': '-', 'modifiers': ['Ctrl'], 'description': 'Zoom Out'},
    'reset_zoom': {'key': '0', 'modifiers': ['Ctrl'], 'description': 'Reset Zoom'},
    
    # Help
    'show_help': {'key': 'F1', 'modifiers': [], 'description': 'Show Help'},
    'show_shortcuts': {'key': 'F1', 'modifiers': ['Ctrl'], 'description': 'Show Keyboard Shortcuts'},
    
    # Application
    'preferences': {'key': 'P', 'modifiers': ['Ctrl'], 'description': 'Preferences'},
    'quit': {'key': 'Q', 'modifiers': ['Ctrl'], 'description': 'Quit'},
    'close_window': {'key': 'W', 'modifiers': ['Ctrl'], 'description': 'Close Window'},
}

# Valid modifier keys
VALID_MODIFIERS = ['Ctrl', 'Alt', 'Shift']

# Special keys that don't require modifiers
SPECIAL_KEYS = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
                'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown',
                'Insert', 'Delete', 'Tab', 'Escape', 'Enter', 'Space']

# Reverse of the key-name map built in _on_shortcut_key_down, used to turn a
# saved shortcut dict back into a wx keycode for building an AcceleratorTable.
_KEY_NAME_TO_WXK = {
    'Up': wx.WXK_UP, 'Down': wx.WXK_DOWN, 'Left': wx.WXK_LEFT, 'Right': wx.WXK_RIGHT,
    'Home': wx.WXK_HOME, 'End': wx.WXK_END, 'PageUp': wx.WXK_PAGEUP, 'PageDown': wx.WXK_PAGEDOWN,
    'Insert': wx.WXK_INSERT, 'Delete': wx.WXK_DELETE, 'Tab': wx.WXK_TAB,
    'Escape': wx.WXK_ESCAPE, 'Enter': wx.WXK_RETURN, 'Space': wx.WXK_SPACE,
    '+': wx.WXK_ADD, '-': wx.WXK_SUBTRACT,
}
for _n in range(1, 13):
    _KEY_NAME_TO_WXK[f'F{_n}'] = getattr(wx, f'WXK_F{_n}')


def shortcut_to_accel(shortcut: Optional[dict]) -> Optional[Tuple[int, int]]:
    """Convert a saved shortcut dict to a (wx.ACCEL_* flags, keycode) pair
    for building a wx.AcceleratorTable entry, or None if unset/invalid."""
    if not shortcut or not shortcut.get('key'):
        return None
    key = shortcut['key']
    if key in _KEY_NAME_TO_WXK:
        keycode = _KEY_NAME_TO_WXK[key]
    elif len(key) == 1:
        keycode = ord(key.upper())
    else:
        return None

    flags = wx.ACCEL_NORMAL
    for mod in shortcut.get('modifiers', []):
        if mod == 'Ctrl':
            flags |= wx.ACCEL_CTRL
        elif mod == 'Alt':
            flags |= wx.ACCEL_ALT
        elif mod == 'Shift':
            flags |= wx.ACCEL_SHIFT
    return (flags, keycode)


class ShortcutEditor(wx.Dialog):
    """Keyboard shortcut editor with conflict detection."""
    
    def __init__(self, parent, config: ConfigManager):
        super().__init__(parent, title="Keyboard Shortcuts", size=(700, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        self.config = config
        self._shortcuts = self._load_shortcuts()
        self._original_shortcuts = self._shortcuts.copy()
        self._conflicts: Dict[str, List[str]] = {}
        
        # Create main sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Instructions
        instructions = wx.StaticText(self, label="Click on a shortcut to edit it. Use Backspace to clear a shortcut. Conflicts will be highlighted in red.")
        instructions.Wrap(650)
        main_sizer.Add(instructions, 0, wx.ALL, 10)
        
        # Create search box
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_sizer.Add(wx.StaticText(self, label="Filter:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.search_txt = wx.TextCtrl(self)
        self.search_txt.SetHint("Search shortcuts...")
        self.search_txt.Bind(wx.EVT_TEXT, self._on_search)
        search_sizer.Add(self.search_txt, 1, wx.EXPAND, 0)
        main_sizer.Add(search_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # Create shortcut list
        self.shortcut_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.shortcut_list.InsertColumn(0, "Action", width=250)
        self.shortcut_list.InsertColumn(1, "Shortcut", width=200)
        self.shortcut_list.InsertColumn(2, "Description", width=200)
        self.shortcut_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_shortcut_selected)
        self.shortcut_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key_down)

        main_sizer.Add(self.shortcut_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Edit controls
        edit_box = wx.StaticBox(self, label="Edit Shortcut")
        edit_sizer = wx.StaticBoxSizer(edit_box, wx.HORIZONTAL)

        edit_sizer.Add(wx.StaticText(edit_box, label="Action:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.action_txt = wx.TextCtrl(edit_box, style=wx.TE_READONLY)
        edit_sizer.Add(self.action_txt, 1, wx.EXPAND | wx.RIGHT, 10)

        edit_sizer.Add(wx.StaticText(edit_box, label="New Shortcut:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.shortcut_txt = wx.TextCtrl(edit_box, style=wx.TE_READONLY)
        self.shortcut_txt.Bind(wx.EVT_KEY_DOWN, self._on_shortcut_key_down)
        edit_sizer.Add(self.shortcut_txt, 1, wx.EXPAND | wx.RIGHT, 10)

        btn_capture = wx.Button(edit_box, label="Capture")
        btn_capture.Bind(wx.EVT_BUTTON, self._on_capture)
        edit_sizer.Add(btn_capture, 0, wx.RIGHT, 10)

        btn_clear = wx.Button(edit_box, label="Clear")
        btn_clear.Bind(wx.EVT_BUTTON, self._on_clear)
        edit_sizer.Add(btn_clear, 0)
        
        main_sizer.Add(edit_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Conflict warning
        self.conflict_warning = wx.StaticText(self, label="", style=wx.ST_NO_AUTORESIZE)
        self.conflict_warning.SetForegroundColour(wx.Colour(255, 0, 0))
        self.conflict_warning.Wrap(650)
        main_sizer.Add(self.conflict_warning, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Populate list -- must come after conflict_warning exists, since
        # _populate_shortcut_list() -> _check_conflicts() references it.
        self._populate_shortcut_list()

        # Buttons
        button_sizer = wx.StdDialogButtonSizer()
        
        btn_ok = wx.Button(self, wx.ID_OK, "OK")
        btn_ok.Bind(wx.EVT_BUTTON, self._on_ok)
        button_sizer.AddButton(btn_ok)
        
        btn_cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        button_sizer.AddButton(btn_cancel)
        
        btn_reset = wx.Button(self, label="Reset to Defaults")
        btn_reset.Bind(wx.EVT_BUTTON, self._on_reset)
        button_sizer.AddButton(btn_reset)
        
        button_sizer.Realize()
        main_sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        
        self.SetSizer(main_sizer)
        self.Layout()
        self.Centre(wx.BOTH)
        
        self._selected_index = -1
    
    def _load_shortcuts(self) -> Dict[str, dict]:
        """Load shortcuts from config or use defaults."""
        saved = self.config.get('shortcuts', default={})
        if not saved:
            return DEFAULT_SHORTCUTS.copy()
        
        # Merge with defaults to ensure all shortcuts exist
        shortcuts = DEFAULT_SHORTCUTS.copy()
        for key, value in saved.items():
            if key in shortcuts:
                shortcuts[key] = value
        return shortcuts
    
    def _format_shortcut(self, shortcut: dict) -> str:
        """Format shortcut dict as display string."""
        if not shortcut or not shortcut.get('key'):
            return "None"
        
        modifiers = shortcut.get('modifiers', [])
        key = shortcut.get('key', '')
        
        parts = modifiers + [key]
        return '+'.join(parts)
    
    def _parse_shortcut(self, shortcut_str: str) -> Optional[dict]:
        """Parse shortcut string into dict."""
        if not shortcut_str or shortcut_str == "None":
            return None
        
        parts = shortcut_str.upper().split('+')
        key = parts[-1]
        modifiers = [p for p in parts[:-1] if p in VALID_MODIFIERS]
        
        # Validate
        if not key:
            return None
        
        # Check if modifier-only shortcut
        if key in VALID_MODIFIERS:
            return None
        
        return {'key': key, 'modifiers': sorted(modifiers)}
    
    def _populate_shortcut_list(self, filter_text: str = "") -> None:
        """Populate the shortcut list with all shortcuts."""
        self.shortcut_list.DeleteAllItems()
        
        index = 0
        for action_id, shortcut in sorted(self._shortcuts.items(), key=lambda x: x[1]['description']):
            description = shortcut['description']
            
            # Apply filter
            if filter_text and filter_text.lower() not in description.lower() and filter_text.lower() not in action_id.lower():
                continue
            
            self.shortcut_list.InsertItem(index, description)
            self.shortcut_list.SetItem(index, 1, self._format_shortcut(shortcut))
            self.shortcut_list.SetItem(index, 2, action_id)
            self.shortcut_list.SetItemData(index, index)
            index += 1
        
        self._check_conflicts()
    
    def _check_conflicts(self) -> None:
        """Check for shortcut conflicts and highlight them."""
        self._conflicts.clear()
        
        # Group shortcuts by key combination
        shortcut_map: Dict[str, List[str]] = {}
        for action_id, shortcut in self._shortcuts.items():
            if shortcut.get('key'):
                key_combo = self._format_shortcut(shortcut)
                if key_combo not in shortcut_map:
                    shortcut_map[key_combo] = []
                shortcut_map[key_combo].append(action_id)
        
        # Find conflicts (more than one action per key combo)
        for key_combo, actions in shortcut_map.items():
            if len(actions) > 1:
                self._conflicts[key_combo] = actions
        
        # Update UI to highlight conflicts
        for i in range(self.shortcut_list.GetItemCount()):
            shortcut_str = self.shortcut_list.GetItem(i, 1).GetText()
            if shortcut_str in self._conflicts:
                self.shortcut_list.SetItemBackgroundColour(i, wx.Colour(255, 200, 200))
            else:
                self.shortcut_list.SetItemBackgroundColour(i, wx.WHITE)
        
        # Update warning message
        if self._conflicts:
            conflict_count = len(self._conflicts)
            self.conflict_warning.SetLabel(f"⚠ {conflict_count} conflict(s) detected. Conflicting shortcuts are highlighted in red.")
        else:
            self.conflict_warning.SetLabel("")
    
    def _on_search(self, event: wx.CommandEvent) -> None:
        """Handle search text change."""
        filter_text = self.search_txt.GetValue()
        self._populate_shortcut_list(filter_text)
    
    def _on_shortcut_selected(self, event: wx.ListEvent) -> None:
        """Handle shortcut list item selection."""
        self._selected_index = event.GetIndex()
        if self._selected_index >= 0:
            action_id = self.shortcut_list.GetItem(self._selected_index, 2).GetText()
            shortcut = self._shortcuts.get(action_id, {})
            
            self.action_txt.SetValue(shortcut.get('description', ''))
            self.shortcut_txt.SetValue(self._format_shortcut(shortcut))
            self.shortcut_txt.SetFocus()
    
    def _on_list_key_down(self, event: wx.KeyEvent) -> None:
        """Handle key events in the shortcut list."""
        if event.GetKeyCode() == wx.WXK_DELETE or event.GetKeyCode() == wx.WXK_BACK:
            # Clear shortcut
            if self._selected_index >= 0:
                action_id = self.shortcut_list.GetItem(self._selected_index, 2).GetText()
                self._shortcuts[action_id] = {'key': '', 'modifiers': [], 'description': self._shortcuts[action_id]['description']}
                self.shortcut_txt.SetValue("None")
                self._populate_shortcut_list(self.search_txt.GetValue())
        else:
            event.Skip()
    
    def _on_shortcut_key_down(self, event: wx.KeyEvent) -> None:
        """Handle key capture in shortcut text box."""
        # Get modifiers
        modifiers = []
        if event.ControlDown():
            modifiers.append('Ctrl')
        if event.AltDown():
            modifiers.append('Alt')
        if event.ShiftDown():
            modifiers.append('Shift')
        
        # Get key
        key_code = event.GetKeyCode()
        key_char = chr(key_code) if 65 <= key_code <= 90 else None
        
        # Map special keys
        key_map = {
            wx.WXK_UP: 'Up',
            wx.WXK_DOWN: 'Down',
            wx.WXK_LEFT: 'Left',
            wx.WXK_RIGHT: 'Right',
            wx.WXK_HOME: 'Home',
            wx.WXK_END: 'End',
            wx.WXK_PAGEUP: 'PageUp',
            wx.WXK_PAGEDOWN: 'PageDown',
            wx.WXK_INSERT: 'Insert',
            wx.WXK_DELETE: 'Delete',
            wx.WXK_TAB: 'Tab',
            wx.WXK_ESCAPE: 'Escape',
            wx.WXK_RETURN: 'Enter',
            wx.WXK_SPACE: 'Space',
        }
        
        key = key_map.get(key_code)
        
        # Function keys
        if wx.WXK_F1 <= key_code <= wx.WXK_F12:
            key = f'F{key_code - wx.WXK_F1 + 1}'
        # Number keys
        elif 48 <= key_code <= 57:
            key = chr(key_code)
        # Letter keys
        elif 65 <= key_code <= 90:
            key = chr(key_code)
        # Special keys
        elif key_code in [wx.WXK_ADD, wx.WXK_SUBTRACT]:
            key = '+' if key_code == wx.WXK_ADD else '-'
        else:
            key = key_map.get(key_code, chr(key_code) if 32 <= key_code <= 126 else None)
        
        if key:
            # Don't allow modifier-only shortcuts
            if key in VALID_MODIFIERS:
                event.Skip()
                return
            
            # Format and display
            shortcut_str = '+'.join(sorted(modifiers) + [key])
            self.shortcut_txt.SetValue(shortcut_str)
            
            # Auto-apply
            if self._selected_index >= 0:
                action_id = self.shortcut_list.GetItem(self._selected_index, 2).GetText()
                self._shortcuts[action_id] = {
                    'key': key,
                    'modifiers': sorted(modifiers),
                    'description': self._shortcuts[action_id]['description']
                }
                self._populate_shortcut_list(self.search_txt.GetValue())
        
        event.Skip()
    
    def _on_capture(self, event: wx.CommandEvent) -> None:
        """Enable shortcut capture mode."""
        self.shortcut_txt.SetFocus()
        self.shortcut_txt.SetValue("Press a key combination...")
    
    def _on_clear(self, event: wx.CommandEvent) -> None:
        """Clear the current shortcut."""
        if self._selected_index >= 0:
            action_id = self.shortcut_list.GetItem(self._selected_index, 2).GetText()
            self._shortcuts[action_id] = {'key': '', 'modifiers': [], 'description': self._shortcuts[action_id]['description']}
            self.shortcut_txt.SetValue("None")
            self._populate_shortcut_list(self.search_txt.GetValue())
    
    def _on_reset(self, event: wx.CommandEvent) -> None:
        """Reset all shortcuts to defaults."""
        dlg = wx.MessageDialog(self, "Reset all shortcuts to default values?", "Reset Shortcuts", 
                              wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self._shortcuts = DEFAULT_SHORTCUTS.copy()
            self._populate_shortcut_list(self.search_txt.GetValue())
            self._selected_index = -1
            self.action_txt.SetValue("")
            self.shortcut_txt.SetValue("")
        dlg.Destroy()
    
    def _on_ok(self, event: wx.CommandEvent) -> None:
        """Handle OK button click."""
        if self._conflicts:
            # Warn about conflicts
            dlg = wx.MessageDialog(self, 
                                  "There are shortcut conflicts. This may cause unexpected behavior. Continue anyway?",
                                  "Conflicts Detected",
                                  wx.YES_NO | wx.ICON_WARNING)
            if dlg.ShowModal() != wx.ID_YES:
                dlg.Destroy()
                return
            dlg.Destroy()
        
        # Save shortcuts
        self.config.set('shortcuts', value=self._shortcuts)
        self.config.save()
        
        self.EndModal(wx.ID_OK)
        self.Destroy()
    
    def get_shortcuts(self) -> Dict[str, dict]:
        """Get the current shortcuts."""
        return self._shortcuts
