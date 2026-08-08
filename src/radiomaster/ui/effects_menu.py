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
                 on_preset: Callable[[str, str, dict[str, Any]], None],
                 get_preset: Callable[[str], str] = lambda eid: "") -> None:
        self._parent = parent
        self._get_params = get_params
        self._is_enabled = is_enabled
        self._on_toggle = on_toggle
        self._on_preset = on_preset
        self._get_preset = get_preset
        self._toggle_items: dict[str, wx.MenuItem] = {}
        # Preset radio items per effect, keyed by preset name -- lets a
        # preset applied programmatically (e.g. via the Preset Manager,
        # which doesn't go through the radio item's own click handling)
        # still get its checkmark synced via set_preset() below.
        self._preset_items: dict[str, dict[str, wx.MenuItem]] = {}
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

        # Radio items (not plain Append) so exactly one preset shows as
        # selected -- AppendRadioItem groups consecutive radio items
        # automatically when the user clicks one, but applying a preset
        # from the Preset Manager dialog bypasses that click handling, so
        # set_preset() below re-syncs the group manually in that case.
        preset_items: dict[str, wx.MenuItem] = {}
        for preset_name, params in BUILTIN_PRESETS.get(effect_id, {}).items():
            preset_id = wx.NewIdRef()
            item = submenu.AppendRadioItem(preset_id, preset_name)
            preset_items[preset_name] = item
            submenu.Bind(
                wx.EVT_MENU,
                lambda e, eid=effect_id, name=preset_name, p=params: self._apply_preset(eid, name, p),
                preset_id,
            )
        self._preset_items[effect_id] = preset_items
        current_preset = self._get_preset(effect_id)
        if current_preset in preset_items:
            self.set_preset(effect_id, current_preset)

        submenu.AppendSeparator()

        manager_id = wx.NewIdRef()
        submenu.Append(manager_id, f"{label} Manager...")
        submenu.Bind(wx.EVT_MENU, lambda e, eid=effect_id: self._open_manager(eid), manager_id)

        return submenu

    def _apply_preset(self, effect_id: str, name: str, params: dict[str, Any]) -> None:
        self._on_preset(effect_id, name, params)
        self.set_enabled(effect_id, True)
        self.set_preset(effect_id, name)

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

    def set_preset(self, effect_id: str, preset_name: str) -> None:
        """Sync the selected-preset radio mark (e.g. after the Preset
        Manager dialog applies a preset without clicking the menu item
        itself). wx doesn't auto-uncheck radio siblings when Check() is
        called programmatically -- only on an actual user click -- so
        every item in the group has to be set explicitly here."""
        for name, item in self._preset_items.get(effect_id, {}).items():
            item.Check(name == preset_name)
