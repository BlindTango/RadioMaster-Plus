"""Full CRUD preset manager for a single effect.

Built-in presets (effects_data.BUILTIN_PRESETS) are read-only -- they can
be applied or used as a starting point for a new custom preset, but not
renamed/edited/deleted. Custom presets are user-created, persisted to
ConfigManager under "effects.custom_presets.<effect_id>", and support the
full CRUD set: Create (New...), Read (the list + Apply), Update
(Edit..., Rename...), Delete.
"""

import wx
from typing import Any, Callable, Optional
from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.utils.config import ConfigManager
from radiomaster.ui.effects_data import BUILTIN_PRESETS, EFFECT_LABELS
from radiomaster.ui.effect_dialog import EffectParamsDialog


class PresetManagerDialog(wx.Dialog):
    """Manage presets (built-in + custom) for one effect.

    *apply_live*, when given, is threaded through to New/Edit's
    EffectParamsDialog as its live-preview callback -- see
    effect_dialog.py's docstring for why that matters."""

    def __init__(self, parent: wx.Window | None, effect_id: str, current_params: dict[str, Any],
                 apply_live: Optional[Callable[[dict[str, Any]], None]] = None) -> None:
        self._effect_id = effect_id
        self._current_params = current_params
        self._apply_live = apply_live
        self._config = ConfigManager.get_instance()
        self._builtin = BUILTIN_PRESETS.get(effect_id, {})
        self._result: Optional[tuple[str, dict[str, Any]]] = None

        title = f"{EFFECT_LABELS[effect_id]} Preset Manager"
        super().__init__(parent, title=title, size=(460, 420))
        self._setup_ui()
        self._refresh_list()
        self.Centre()

    # ------------------------------------------------------------------
    def _custom_presets(self) -> dict[str, dict[str, Any]]:
        return self._config.get(f"effects.custom_presets.{self._effect_id}", default={})

    def _save_custom_presets(self, presets: dict[str, dict[str, Any]]) -> None:
        self._config.set(f"effects.custom_presets.{self._effect_id}", value=presets)
        self._config.save()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(self, label="Presets:"), 0, wx.ALL, 5)
        # wx.ListBox instead of wx.ListCtrl here (unlike every other list
        # in the app) was reported as inaccessible to a screen reader --
        # switched to the same LC_REPORT single-column ListCtrl pattern
        # used everywhere else (e.g. theme_editor.py's color list,
        # settings_dialog.py's category list) for consistent, working
        # accessibility.
        self._preset_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_NO_HEADER)
        set_accessible_name(self._preset_list, "Preset List")
        self._preset_list.InsertColumn(0, "Preset")
        self._preset_list.Bind(wx.EVT_SIZE, self._on_preset_list_resize)
        sizer.Add(self._preset_list, 1, wx.EXPAND | wx.ALL, 5)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_apply = wx.Button(self, label="&Apply")
        set_accessible_name(self._btn_apply, "Apply Preset")
        self._btn_apply.Bind(wx.EVT_BUTTON, self._on_apply)
        row1.Add(self._btn_apply, 0, wx.RIGHT, 5)

        self._btn_new = wx.Button(self, label="&New...")
        set_accessible_name(self._btn_new, "New Preset")
        self._btn_new.Bind(wx.EVT_BUTTON, self._on_new)
        row1.Add(self._btn_new, 0, wx.RIGHT, 5)

        self._btn_edit = wx.Button(self, label="&Edit...")
        set_accessible_name(self._btn_edit, "Edit Preset")
        self._btn_edit.Bind(wx.EVT_BUTTON, self._on_edit)
        row1.Add(self._btn_edit, 0, wx.RIGHT, 5)

        sizer.Add(row1, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_rename = wx.Button(self, label="&Rename...")
        set_accessible_name(self._btn_rename, "Rename Preset")
        self._btn_rename.Bind(wx.EVT_BUTTON, self._on_rename)
        row2.Add(self._btn_rename, 0, wx.RIGHT, 5)

        self._btn_delete = wx.Button(self, label="&Delete")
        set_accessible_name(self._btn_delete, "Delete Preset")
        self._btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
        row2.Add(self._btn_delete, 0, wx.RIGHT, 5)

        sizer.Add(row2, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        close_btn = wx.Button(self, label="Close", id=wx.ID_CLOSE)
        set_accessible_name(close_btn, "Close")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        self.SetSizer(sizer)
        self._preset_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._update_button_states())
        self._preset_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._update_button_states())
        # wx.ID_CLOSE (unlike wx.ID_CANCEL) doesn't get automatic
        # Escape-closes-dialog behavior, so bind it explicitly.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    def _on_preset_list_resize(self, event: wx.SizeEvent) -> None:
        event.Skip()
        self._preset_list.SetColumnWidth(0, self._preset_list.GetClientSize().width)

    # ------------------------------------------------------------------
    def _select_index(self, index: int) -> None:
        state = wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED
        self._preset_list.SetItemState(index, state, state)
        self._preset_list.EnsureVisible(index)

    def _refresh_list(self, select: str | None = None) -> None:
        self._preset_list.DeleteAllItems()
        for name in self._builtin:
            self._preset_list.Append((f"{name} (built-in)",))
        for name in self._custom_presets():
            self._preset_list.Append((name,))
        if select:
            idx = self._find_index(select)
            if idx >= 0:
                self._select_index(idx)
        elif self._preset_list.GetItemCount():
            self._select_index(0)
        self._update_button_states()

    def _find_index(self, name: str) -> int:
        for i in range(self._preset_list.GetItemCount()):
            if self._selected_name_at(i) == name:
                return i
        return -1

    def _selected_name_at(self, index: int) -> str:
        label = self._preset_list.GetItemText(index, 0)
        return label[: -len(" (built-in)")] if label.endswith(" (built-in)") else label

    def _selected_name(self) -> str | None:
        idx = self._preset_list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return None
        return self._selected_name_at(idx)

    def _is_builtin(self, name: str) -> bool:
        return name in self._builtin

    def _params_for(self, name: str) -> dict[str, Any]:
        if name in self._builtin:
            return self._builtin[name]
        return self._custom_presets().get(name, {})

    def _update_button_states(self) -> None:
        name = self._selected_name()
        has_selection = name is not None
        is_custom = has_selection and not self._is_builtin(name)
        self._btn_apply.Enable(has_selection)
        self._btn_edit.Enable(is_custom)
        self._btn_rename.Enable(is_custom)
        self._btn_delete.Enable(is_custom)

    # ------------------------------------------------------------------
    def _on_apply(self, event: wx.CommandEvent) -> None:
        name = self._selected_name()
        if name is None:
            return
        self._result = (name, dict(self._params_for(name)))
        self.EndModal(wx.ID_OK)

    def _on_new(self, event: wx.CommandEvent) -> None:
        seed = self._params_for(self._selected_name()) if self._selected_name() else self._current_params
        param_dlg = EffectParamsDialog(self, self._effect_id, seed, title="New Preset",
                                        on_live_change=self._apply_live)
        if param_dlg.ShowModal() != wx.ID_OK:
            param_dlg.Destroy()
            return
        params = param_dlg.get_params()
        param_dlg.Destroy()

        name_dlg = wx.TextEntryDialog(self, "Enter preset name:", "New Preset")
        if name_dlg.ShowModal() == wx.ID_OK:
            name = name_dlg.GetValue().strip()
            if name and name not in self._builtin:
                presets = self._custom_presets()
                presets[name] = params
                self._save_custom_presets(presets)
                self._refresh_list(select=name)
            elif name in self._builtin:
                wx.MessageBox(f'"{name}" is a built-in preset name and can\'t be reused.',
                               "Name Unavailable", wx.OK | wx.ICON_WARNING, self)
        name_dlg.Destroy()

    def _on_edit(self, event: wx.CommandEvent) -> None:
        name = self._selected_name()
        if not name or self._is_builtin(name):
            return
        param_dlg = EffectParamsDialog(self, self._effect_id, self._params_for(name),
                                        title=f"Edit '{name}'", on_live_change=self._apply_live)
        if param_dlg.ShowModal() == wx.ID_OK:
            presets = self._custom_presets()
            presets[name] = param_dlg.get_params()
            self._save_custom_presets(presets)
            self._refresh_list(select=name)
        param_dlg.Destroy()

    def _on_rename(self, event: wx.CommandEvent) -> None:
        name = self._selected_name()
        if not name or self._is_builtin(name):
            return
        dlg = wx.TextEntryDialog(self, "New name:", "Rename Preset", value=name)
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if new_name and new_name != name and new_name not in self._builtin:
                presets = self._custom_presets()
                presets[new_name] = presets.pop(name, {})
                self._save_custom_presets(presets)
                self._refresh_list(select=new_name)
        dlg.Destroy()

    def _on_delete(self, event: wx.CommandEvent) -> None:
        name = self._selected_name()
        if not name or self._is_builtin(name):
            return
        confirm = wx.MessageDialog(self, f"Delete preset '{name}'?", "Confirm",
                                    wx.YES_NO | wx.ICON_QUESTION)
        if confirm.ShowModal() == wx.ID_YES:
            presets = self._custom_presets()
            presets.pop(name, None)
            self._save_custom_presets(presets)
            self._refresh_list()
        confirm.Destroy()

    # ------------------------------------------------------------------
    def get_result(self) -> Optional[tuple[str, dict[str, Any]]]:
        """(preset_name, params) if Apply was pressed, else None."""
        return self._result
