"""Top-level "Effects" menu: one submenu per effect, each with an On/Off
toggle, its preset list, and a "<Effect> Manager..." entry with full CRUD
(see preset_manager_dialog.py).

This is a real wx.MenuBar top-level menu -- opened by the OS the normal
way (mouse click on the menu bar, or Alt+E), not something a button needs
to "open" programmatically. An earlier version had a dedicated FX button
in the transport bar that tried to pop the menu open via
menu.UpdateUI() -- that call only refreshes checkmark state and doesn't
display anything, so the button silently did nothing. That button has
been removed; the menu bar entry itself has always worked when clicked
directly.
"""

import wx
from typing import Any, Callable
from radiomaster.ui.effects_data import EFFECT_IDS, EFFECT_LABELS, BUILTIN_PRESETS


class EffectsMenu:
    """Builds and manages the Effects menu and its submenus."""

    def __init__(self, parent: wx.MenuBar, get_params: Callable[[str], dict[str, Any]],
                 is_enabled: Callable[[str], bool],
                 on_toggle: Callable[[str, bool], None],
                 on_preset: Callable[[str, str, dict[str, Any]], None]) -> None:
        self._parent = parent
        self._get_params = get_params
        self._is_enabled = is_enabled
        self._on_toggle = on_toggle
        self._on_preset = on_preset
        self._toggle_items: dict[str, wx.MenuItem] = {}
        self._menu = wx.Menu()
        self._build_menu()
        parent.Append(self._menu, "&Effects")

    def _build_menu(self) -> None:
        for i, effect_id in enumerate(EFFECT_IDS):
            if i > 0:
                self._menu.AppendSeparator()
            submenu = self._build_effect_submenu(effect_id)
            self._menu.AppendSubMenu(submenu, EFFECT_LABELS[effect_id])

    def _build_effect_submenu(self, effect_id: str) -> wx.Menu:
        submenu = wx.Menu()
        label = EFFECT_LABELS[effect_id]

        toggle_item = submenu.AppendCheckItem(wx.ID_ANY, "On/Off")
        toggle_item.Check(self._is_enabled(effect_id))
        self._toggle_items[effect_id] = toggle_item
        submenu.Bind(
            wx.EVT_MENU,
            lambda e, eid=effect_id, item=toggle_item: self._on_toggle(eid, item.IsChecked()),
            toggle_item,
        )

        submenu.AppendSeparator()

        for preset_name, params in BUILTIN_PRESETS.get(effect_id, {}).items():
            preset_id = wx.NewIdRef()
            submenu.Append(preset_id, preset_name)
            submenu.Bind(
                wx.EVT_MENU,
                lambda e, eid=effect_id, name=preset_name, p=params: self._apply_preset(eid, name, p),
                preset_id,
            )

        submenu.AppendSeparator()

        manager_id = wx.NewIdRef()
        submenu.Append(manager_id, f"{label} Manager...")
        submenu.Bind(wx.EVT_MENU, lambda e, eid=effect_id: self._open_manager(eid), manager_id)

        return submenu

    def _apply_preset(self, effect_id: str, name: str, params: dict[str, Any]) -> None:
        self._on_preset(effect_id, name, params)
        self.set_enabled(effect_id, True)

    def _open_manager(self, effect_id: str) -> None:
        from radiomaster.ui.preset_manager_dialog import PresetManagerDialog
        dlg = PresetManagerDialog(None, effect_id, self._get_params(effect_id))
        if dlg.ShowModal() == wx.ID_OK:
            result = dlg.get_result()
            if result:
                name, params = result
                self._apply_preset(effect_id, name, params)
        dlg.Destroy()

    def set_enabled(self, effect_id: str, enabled: bool) -> None:
        """Sync the On/Off checkmark (e.g. after a preset auto-enables)."""
        item = self._toggle_items.get(effect_id)
        if item:
            item.Check(enabled)
