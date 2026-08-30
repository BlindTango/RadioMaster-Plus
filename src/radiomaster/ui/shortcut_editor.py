"""Accessible keyboard shortcut catalogue and CRUD editor."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import wx

from radiomaster.utils.accessibility import set_accessible_name

if TYPE_CHECKING:
    from radiomaster.utils.config import ConfigManager


def _a(category: str, name: str, key: str = "", *mods: str) -> dict:
    return {
        "category": category,
        "description": name,
        "key": key,
        "modifiers": list(mods),
        "global": False,
    }


# Single source of truth for the dialog and MainWindow accelerator table.
DEFAULT_SHORTCUTS: dict[str, dict] = {
    "play_pause": _a("Playback controls", "Play or pause", "P", "Left Ctrl"),
    "stop": _a("Playback controls", "Stop", "S", "Left Ctrl", "Left Shift"),
    "volume_up": _a("Playback controls", "Volume up", "Up", "Left Ctrl"),
    "volume_down": _a("Playback controls", "Volume down", "Down", "Left Ctrl"),
    "mute": _a("Playback controls", "Mute or unmute", "M", "Left Ctrl"),
    "seek_forward": _a("Playback controls", "Fast forward 10 seconds", "Right", "Left Ctrl"),
    "seek_backward": _a("Playback controls", "Rewind 10 seconds", "Left", "Left Ctrl"),
    "rate_up": _a("Playback controls", "Playback rate up", "]", "Left Ctrl"),
    "rate_down": _a("Playback controls", "Playback rate down", "[", "Left Ctrl"),
    "speed_up": _a("Playback controls", "Playback speed up"),
    "speed_down": _a("Playback controls", "Playback speed down"),
    "pan_left": _a("Playback controls", "Pan left", "[", "Left Alt"),
    "pan_right": _a("Playback controls", "Pan right", "]", "Left Alt"),
    "first_track": _a("Playback controls", "First item or station", "Home", "Left Ctrl"),
    "previous_track": _a("Playback controls", "Previous item or station", "PageUp", "Left Ctrl"),
    "next_track": _a("Playback controls", "Next item or station", "PageDown", "Left Ctrl"),
    "last_track": _a("Playback controls", "Last item or station", "End", "Left Ctrl"),
    "record": _a(
        "Playback controls", "Start or stop radio recording", "R", "Left Ctrl", "Left Shift"
    ),
    "next_tab": _a("Panels", "Next panel", "Tab", "Left Ctrl"),
    "previous_tab": _a("Panels", "Previous panel", "Tab", "Left Ctrl", "Left Shift"),
    **{
        f"panel_{name}": _a("Panels", f"{label} panel", str(i), "Left Ctrl")
        for i, (name, label) in enumerate(
            [
                ("radio", "Radio"),
                ("podcasts", "Podcasts"),
                ("audiobooks", "Audiobooks"),
                ("media", "Media Player"),
                ("youtube", "YouTube"),
                ("downloads", "Downloads"),
                ("scheduler", "Scheduler"),
            ],
            1,
        )
    },
    "search": _a("Panels", "Focus global search", "F", "Left Ctrl"),
    "open_file": _a("File menu", "Open file", "O", "Left Ctrl"),
    "open_url": _a("File menu", "Open URL", "U", "Left Ctrl"),
    "open_folder": _a("File menu", "Open folder", "O", "Left Ctrl", "Left Shift"),
    "import_opml": _a("File menu", "Import OPML"),
    "export_opml": _a("File menu", "Export OPML"),
    "exit": _a("File menu", "Exit RadioMaster+", "F4", "Left Alt"),
    "toggle_equalizer": _a("View menu", "Toggle equalizer", "E", "Left Ctrl", "Left Shift"),
    "toggle_lyrics": _a("View menu", "Toggle lyrics panel", "L", "Left Ctrl"),
    "toggle_fullscreen": _a("View menu", "Toggle fullscreen", "F11"),
    "theme_light": _a("View menu", "Use Default Light theme"),
    "theme_dark": _a("View menu", "Use Default Dark theme"),
    "theme_editor": _a("View menu", "Open Theme Editor"),
    "language_english": _a("View menu", "Use English language"),
    **{
        f"effect_{name}": _a("Effects menu", f"Toggle {label} effect")
        for name, label in [
            ("echo", "Echo"),
            ("equalizer", "Equalizer"),
            ("reverb", "Reverb"),
            ("dynamic_range", "Dynamic Range"),
            ("pitch_tempo", "Pitch/Tempo Shift"),
            ("chorus", "Chorus"),
            ("compressor", "Compressor"),
            ("distortion", "Distortion"),
            ("flanger", "Flanger"),
            ("gargle", "Gargle"),
        ]
    },
    "sleep_timer": _a("Tools menu", "Open Sleep Timer", "T", "Left Ctrl"),
    "download_manager": _a("Tools menu", "Open Download Manager", "D", "Left Ctrl"),
    "recording_scheduler": _a("Tools menu", "Open Recording Scheduler", "R", "Left Ctrl"),
    "track_identifier": _a("Tools menu", "Open Track Identifier", "I", "Left Ctrl"),
    "track_splitter": _a("Tools menu", "Open Track Splitter"),
    "keyboard_shortcuts": _a("Tools menu", "Open Keyboard Shortcuts", "K", "Left Ctrl"),
    "settings": _a("Tools menu", "Open Settings", ",", "Left Ctrl"),
    "user_manual": _a("Help menu", "Open User Manual", "F1"),
    "quick_start": _a("Help menu", "Open Quick Start Guide"),
    "release_notes": _a("Help menu", "Open Release Notes"),
    "update_ytdlp": _a("Help menu", "Update YouTube Library"),
    "check_updates": _a("Help menu", "Check for updates"),
    "about": _a("Help menu", "About RadioMaster+"),
}

MODIFIERS = (
    "Left Shift",
    "Right Shift",
    "Left Ctrl",
    "Right Ctrl",
    "Left Windows",
    "Right Windows",
    "Left Alt",
    "Right Alt",
)
KEYS = (
    [chr(c) for c in range(65, 91)]
    + [str(n) for n in range(10)]
    + [f"F{n}" for n in range(1, 25)]
    + [
        "Escape",
        "Tab",
        "Caps Lock",
        "Space",
        "Enter",
        "Backspace",
        "Insert",
        "Delete",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Up",
        "Down",
        "Left",
        "Right",
        "Print Screen",
        "Scroll Lock",
        "Pause",
        "`",
        "-",
        "=",
        "[",
        "]",
        "\\",
        ";",
        "'",
        ",",
        ".",
        "/",
    ]
    + [f"Numpad {n}" for n in range(10)]
    + [
        "Numpad Add",
        "Numpad Subtract",
        "Numpad Multiply",
        "Numpad Divide",
        "Numpad Decimal",
        "Numpad Enter",
    ]
)

_WX_KEYS = {
    "Escape": wx.WXK_ESCAPE,
    "Tab": wx.WXK_TAB,
    "Space": wx.WXK_SPACE,
    "Enter": wx.WXK_RETURN,
    "Backspace": wx.WXK_BACK,
    "Insert": wx.WXK_INSERT,
    "Delete": wx.WXK_DELETE,
    "Home": wx.WXK_HOME,
    "End": wx.WXK_END,
    "PageUp": wx.WXK_PAGEUP,
    "PageDown": wx.WXK_PAGEDOWN,
    "Up": wx.WXK_UP,
    "Down": wx.WXK_DOWN,
    "Left": wx.WXK_LEFT,
    "Right": wx.WXK_RIGHT,
    "Pause": wx.WXK_PAUSE,
    "Numpad Add": wx.WXK_NUMPAD_ADD,
    "Numpad Subtract": wx.WXK_NUMPAD_SUBTRACT,
    "Numpad Multiply": wx.WXK_NUMPAD_MULTIPLY,
    "Numpad Divide": wx.WXK_NUMPAD_DIVIDE,
    "Numpad Decimal": wx.WXK_NUMPAD_DECIMAL,
    "Numpad Enter": wx.WXK_NUMPAD_ENTER,
}
for _n in range(1, 25):
    if (value := getattr(wx, f"WXK_F{_n}", None)) is not None:
        _WX_KEYS[f"F{_n}"] = value
for _n in range(10):
    _WX_KEYS[f"Numpad {_n}"] = getattr(wx, f"WXK_NUMPAD{_n}")


def format_shortcut(shortcut: dict) -> str:
    return (
        "+".join([*shortcut.get("modifiers", []), shortcut.get("key", "")])
        if shortcut.get("key")
        else "Unassigned"
    )


def shortcut_signature(shortcut: dict) -> tuple[tuple[str, ...], str]:
    families = {
        family
        for modifier in shortcut.get("modifiers", [])
        for family in ("Ctrl", "Shift", "Alt", "Windows")
        if modifier == family or modifier.endswith(family)
    }
    return tuple(sorted(families)), shortcut.get("key", "")


def find_conflict(shortcuts: dict[str, dict], candidate: dict, exclude: str = "") -> str | None:
    signature = shortcut_signature(candidate)
    return next(
        (
            action
            for action, value in shortcuts.items()
            if action != exclude and value.get("key") and shortcut_signature(value) == signature
        ),
        None,
    )


def shortcut_to_accel(shortcut: dict | None) -> tuple[int, int] | None:
    if not shortcut or not shortcut.get("key"):
        return None
    modifiers, key = shortcut_signature(shortcut)
    if "Windows" in modifiers:
        return None
    keycode = _WX_KEYS.get(key, ord(key.upper()) if len(key) == 1 else None)
    if keycode is None:
        return None
    flags = wx.ACCEL_NORMAL
    flags |= wx.ACCEL_CTRL if "Ctrl" in modifiers else 0
    flags |= wx.ACCEL_SHIFT if "Shift" in modifiers else 0
    flags |= wx.ACCEL_ALT if "Alt" in modifiers else 0
    return flags, keycode


def shortcut_to_global_spec(shortcut: dict) -> str | None:
    """Convert an assignment to the format used by RegisterHotKey."""
    if not shortcut.get("key"):
        return None
    modifiers, key = shortcut_signature(shortcut)
    key_aliases = {
        "PageUp": "PAGEUP",
        "PageDown": "PAGEDOWN",
        "Numpad Add": None,
        "Numpad Subtract": None,
        "Numpad Multiply": None,
        "Numpad Divide": None,
        "Numpad Decimal": None,
        "Numpad Enter": None,
        "Caps Lock": None,
        "Print Screen": None,
        "Scroll Lock": None,
        "Backspace": None,
    }
    token = key_aliases.get(key, key)
    if key.startswith("F") and key[1:].isdigit() and int(key[1:]) > 12:
        return None
    if token is None or (len(token) == 1 and not token.isalnum()) or key.startswith("Numpad "):
        return None
    parts = [name for name in ("Ctrl", "Alt", "Shift", "Windows") if name in modifiers]
    return "+".join([*parts, token])


def load_shortcuts(config: ConfigManager) -> dict[str, dict]:
    result = deepcopy(DEFAULT_SHORTCUTS)
    legacy_names = {
        "toggle_sleep_timer": "sleep_timer",
        "preferences": "settings",
        "quit": "exit",
        "show_help": "user_manual",
        "show_shortcuts": "keyboard_shortcuts",
        "start_recording": "record",
        "stop_recording": "record",
    }
    for action, saved in (config.get("shortcuts", default={}) or {}).items():
        action = legacy_names.get(action, action)
        if action in result and isinstance(saved, dict):
            candidate = {
                "key": saved.get("key", ""),
                "modifiers": list(saved.get("modifiers", [])),
                "global": bool(saved.get("global", False)),
            }
            # Old releases shipped conflicting defaults. Do not import one
            # of those collisions into the new conflict-free catalogue.
            if not candidate["key"] or not find_conflict(result, candidate, action):
                result[action].update(candidate)
    return result


class ShortcutAssignmentDialog(wx.Dialog):
    def __init__(self, parent, shortcuts: dict[str, dict], action_id: str = "") -> None:
        super().__init__(
            parent,
            title="Edit Keyboard Shortcut" if action_id else "New Keyboard Shortcut",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.shortcuts, self.editing, self.action_ids = (
            shortcuts,
            action_id,
            list(DEFAULT_SHORTCUTS),
        )
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            self, label="Choose a feature, main key, and modifiers. Each shortcut must be unique."
        )
        root.Add(intro, 0, wx.ALL, 12)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="&Feature:"), 0, wx.ALIGN_CENTER_VERTICAL)
        labels = [
            f"{DEFAULT_SHORTCUTS[a]['category']}: {DEFAULT_SHORTCUTS[a]['description']}"
            for a in self.action_ids
        ]
        self.feature = wx.Choice(self, choices=labels)
        set_accessible_name(self.feature, "Feature")
        grid.Add(self.feature, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="&Main key:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.key = wx.Choice(self, choices=KEYS)
        set_accessible_name(self.key, "Main key")
        grid.Add(self.key, 1, wx.EXPAND)
        root.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        box = wx.StaticBoxSizer(wx.StaticBox(self, label="Modifier keys"), wx.VERTICAL)
        mod_grid = wx.GridSizer(cols=2, vgap=4, hgap=20)
        self.checks = {}
        for label in MODIFIERS:
            check = wx.CheckBox(box.GetStaticBox(), label=label)
            set_accessible_name(check, f"{label} modifier")
            check.Bind(wx.EVT_CHECKBOX, self._changed)
            self.checks[label] = check
            mod_grid.Add(check)
        box.Add(mod_grid, 0, wx.ALL | wx.EXPAND, 8)
        root.Add(box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.global_check = wx.CheckBox(
            self,
            label="&Global shortcut (works when RadioMaster+ is not focused)",
        )
        set_accessible_name(self.global_check, "Global shortcut")
        self.global_check.Bind(wx.EVT_CHECKBOX, self._changed)
        root.Add(self.global_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.status = wx.StaticText(self, label="Select a main key.", style=wx.ST_NO_AUTORESIZE)
        set_accessible_name(self.status, "Shortcut validation status")
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        buttons = wx.StdDialogButtonSizer()
        self.ok = wx.Button(self, wx.ID_OK, "&Save" if action_id else "&Create")
        buttons.AddButton(self.ok)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL))
        buttons.Realize()
        root.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizerAndFit(root)
        self.SetMinSize((650, self.GetSize().height))
        self.feature.SetSelection(0)
        self.feature.Bind(wx.EVT_CHOICE, self._changed)
        self.key.Bind(wx.EVT_CHOICE, self._changed)
        self.ok.Bind(wx.EVT_BUTTON, self._on_ok)
        if action_id:
            self.feature.SetSelection(self.action_ids.index(action_id))
            self.feature.Disable()
            current = shortcuts[action_id]
            self.key.SetStringSelection(current.get("key", ""))
            for modifier in current.get("modifiers", []):
                if modifier in self.checks:
                    self.checks[modifier].SetValue(True)
            self.global_check.SetValue(bool(current.get("global", False)))
        self._validate()
        wx.CallAfter(self.key.SetFocus if action_id else self.feature.SetFocus)

    def selection(self) -> tuple[str, dict]:
        index = self.feature.GetSelection()
        action = self.action_ids[index] if index != wx.NOT_FOUND else ""
        return action, {
            "key": self.key.GetStringSelection(),
            "modifiers": [m for m in MODIFIERS if self.checks[m].GetValue()],
            "global": self.global_check.GetValue(),
        }

    def _validate(self) -> bool:
        action, candidate = self.selection()
        valid = bool(action and candidate["key"])
        message = "Shortcut is available."
        if not valid:
            message = "Select a feature and main key."
        elif candidate["global"] and shortcut_to_global_spec(candidate) is None:
            valid, message = (
                False,
                "This main key cannot be registered globally. Choose a letter, number, "
                "function key, arrow, navigation key, Space, Enter, Escape, Tab, or Pause.",
            )
        elif not candidate["global"] and any(
            m.endswith("Windows") for m in candidate["modifiers"]
        ):
            valid, message = (
                False,
                "Windows logo modifiers require the Global shortcut checkbox.",
            )
        elif conflict := find_conflict(self.shortcuts, candidate, self.editing or action):
            valid, message = (
                False,
                f"Unavailable: already assigned to {DEFAULT_SHORTCUTS[conflict]['description']}.",
            )
        self.status.SetLabel(message)
        self.ok.Enable(valid)
        return valid

    def _changed(self, event):
        self._validate()
        event.Skip()

    def _on_ok(self, event):
        if self._validate():
            self.EndModal(wx.ID_OK)


class ShortcutEditor(wx.Dialog):
    def __init__(self, parent, config: ConfigManager):
        super().__init__(
            parent,
            title="Keyboard Shortcuts",
            size=(850, 650),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.config, self._shortcuts, self._visible = config, load_shortcuts(config), []
        root = wx.BoxSizer(wx.VERTICAL)
        text = wx.StaticText(
            self,
            label=(
                "Manage shortcuts for menus, panels, and playback controls. "
                "New assigns, Edit changes, and Delete unassigns."
            ),
        )
        root.Add(text, 0, wx.ALL | wx.EXPAND, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(
            wx.StaticText(self, label="&Filter features:"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            6,
        )
        self.search = wx.TextCtrl(self)
        self.search.SetHint("Feature, category, or shortcut")
        set_accessible_name(self.search, "Filter features")
        self.search.Bind(wx.EVT_TEXT, lambda e: self._populate())
        row.Add(self.search, 1, wx.EXPAND)
        root.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        set_accessible_name(self.list, "Keyboard shortcut assignments")
        for column, (label, width) in enumerate(
            (("Feature", 290), ("Shortcut", 220), ("Scope", 90), ("Category", 190))
        ):
            self.list.InsertColumn(column, label, width=width)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._selection_changed)
        self.list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._selection_changed)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._edit)
        self.list.Bind(wx.EVT_KEY_DOWN, self._list_key)
        root.Add(self.list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.new = wx.Button(self, label="&New...")
        self.edit = wx.Button(self, label="&Edit...")
        self.delete = wx.Button(self, label="&Delete")
        reset = wx.Button(self, label="&Reset All to Defaults")
        for button in (self.new, self.edit, self.delete, reset):
            actions.Add(button, 0, wx.RIGHT, 8)
        self.new.Bind(wx.EVT_BUTTON, self._new)
        self.edit.Bind(wx.EVT_BUTTON, self._edit)
        self.delete.Bind(wx.EVT_BUTTON, self._delete)
        reset.Bind(wx.EVT_BUTTON, self._reset)
        root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        buttons = wx.StdDialogButtonSizer()
        save = wx.Button(self, wx.ID_OK, "&Save and Close")
        save.Bind(wx.EVT_BUTTON, self._save)
        buttons.AddButton(save)
        buttons.AddButton(wx.Button(self, wx.ID_CANCEL))
        buttons.Realize()
        root.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        self.SetSizer(root)
        self._populate()
        self._update_buttons()
        self.CentreOnParent()
        wx.CallAfter(self.list.SetFocus)

    def _selected(self) -> str:
        index = self.list.GetFirstSelected()
        return self._visible[index] if 0 <= index < len(self._visible) else ""

    def _populate(self):
        query = self.search.GetValue().strip().casefold()
        self.list.DeleteAllItems()
        self._visible = []
        for action, item in sorted(
            self._shortcuts.items(), key=lambda pair: (pair[1]["category"], pair[1]["description"])
        ):
            display = format_shortcut(item)
            scope = "Global" if item.get("global") else "In app"
            if (
                query
                and query
                not in (
                    f"{item['description']} {item['category']} {display} {scope} {action}"
                ).casefold()
            ):
                continue
            row = self.list.InsertItem(self.list.GetItemCount(), item["description"])
            self.list.SetItem(row, 1, display)
            self.list.SetItem(row, 2, scope)
            self.list.SetItem(row, 3, item["category"])
            self._visible.append(action)
        self._update_buttons()

    def _update_buttons(self):
        action = self._selected()
        self.edit.Enable(bool(action))
        self.delete.Enable(bool(action and self._shortcuts[action].get("key")))

    def _selection_changed(self, event):
        self._update_buttons()
        event.Skip()

    def _list_key(self, event):
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_BACK):
            self._delete(event)
        else:
            event.Skip()

    def _show_assignment(self, action=""):
        dialog = ShortcutAssignmentDialog(self, self._shortcuts, action)
        if dialog.ShowModal() == wx.ID_OK:
            action, value = dialog.selection()
            self._shortcuts[action].update(value)
            self._populate()
        dialog.Destroy()

    def _new(self, event):
        self._show_assignment()

    def _edit(self, event):
        if action := self._selected():
            self._show_assignment(action)

    def _delete(self, event):
        if action := self._selected():
            self._shortcuts[action].update({"key": "", "modifiers": [], "global": False})
            self._populate()

    def _reset(self, event):
        dialog = wx.MessageDialog(
            self,
            "Reset every keyboard shortcut to its default?",
            "Reset Keyboard Shortcuts",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if dialog.ShowModal() == wx.ID_YES:
            self._shortcuts = deepcopy(DEFAULT_SHORTCUTS)
            self._populate()
        dialog.Destroy()

    def _save(self, event):
        self.config.set("shortcuts", value=self._shortcuts)
        self.config.save()
        self.EndModal(wx.ID_OK)

    def get_shortcuts(self) -> dict[str, dict]:
        return deepcopy(self._shortcuts)
