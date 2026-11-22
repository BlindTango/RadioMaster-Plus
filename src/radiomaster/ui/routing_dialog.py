"""Edit the country routes used by Regional routing (Settings > Network)."""

from __future__ import annotations

import json

import wx

from radiomaster.services.routing import (
    METHOD_LABELS, METHODS, Route, find_expressvpn, find_tailscale, run_command)
from radiomaster.services.vpn_regions import arrange, move, regions_for_country
from radiomaster.utils.accessibility import set_accessible_name

_TARGET_HELP = {
    "expressvpn": ("ExpressVPN &region(s), separated by commas:",
                   "ExpressVPN regions in order, for example uk-london, uk-manchester"),
    "tailscale": ("Tailscale &exit node(s), separated by commas:",
                  "Tailscale exit node names or addresses in order"),
    "command": ("&Connect command:", "Command that connects the VPN to this country"),
}


def known_countries() -> list[str]:
    try:
        from radiomaster.services.station_db import StationDB
        return [name for name, _count in StationDB().country_groups() if name]
    except Exception:
        return []


def expressvpn_regions() -> list[str]:
    exe = find_expressvpn()
    if not exe:
        return []
    try:
        code, out = run_command([exe, "get", "regions"], timeout=10)
    except Exception:
        return []
    return [line.strip() for line in out.replace(",", "\n").split() if line.strip()] if code == 0 else []


def tailscale_exit_nodes() -> list[str]:
    """Names of the machines on your tailnet that offer to be exit nodes."""
    exe = find_tailscale()
    if not exe:
        return []
    try:
        code, out = run_command([exe, "status", "--json"], timeout=10)
        peers = (json.loads(out).get("Peer") or {}).values() if code == 0 else []
    except Exception:
        return []
    return sorted({str(peer.get("HostName") or "").strip() for peer in peers
                   if peer.get("ExitNodeOption") and peer.get("HostName")})


class RouteEditDialog(wx.Dialog):
    def __init__(self, parent, route: Route | None = None, countries: list[str] | None = None):
        super().__init__(parent, title="Edit Route" if route else "Add Route",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        layout = wx.BoxSizer(wx.VERTICAL)

        layout.Add(wx.StaticText(self, label="&Country the station is from:"), 0, wx.ALL, 8)
        self.country = wx.ComboBox(self, choices=countries or [], value=route.country if route else "")
        set_accessible_name(self.country, "Country the station is from")
        layout.Add(self.country, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        layout.Add(wx.StaticText(self, label="Connect &using:"), 0, wx.ALL, 8)
        self.method = wx.Choice(self, choices=[METHOD_LABELS[m] for m in METHODS])
        set_accessible_name(self.method, "Connect using")
        self.method.SetSelection(METHODS.index(route.method) if route else 0)
        layout.Add(self.method, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Servers: a checkable, orderable list when the VPN can tell us its servers ...
        self.servers_label = wx.StaticText(self, label="&Servers to try, in this order (check the ones you want):")
        layout.Add(self.servers_label, 0, wx.ALL, 8)
        list_row = wx.BoxSizer(wx.HORIZONTAL)
        self.servers = wx.CheckListBox(self, size=(300, 170))
        set_accessible_name(self.servers, "Servers to try, in this order. Space checks or unchecks one; "
                            "Alt plus Up or Down arrow moves it")
        list_row.Add(self.servers, 1, wx.EXPAND | wx.RIGHT, 8)
        side = wx.BoxSizer(wx.VERTICAL)
        self.up_btn = wx.Button(self, label="Move &Up")
        self.down_btn = wx.Button(self, label="Move &Down")
        set_accessible_name(self.up_btn, "Move the selected server up, to be tried earlier")
        set_accessible_name(self.down_btn, "Move the selected server down, to be tried later")
        side.Add(self.up_btn, 0, wx.BOTTOM, 6)
        side.Add(self.down_btn, 0)
        list_row.Add(side, 0)
        self.list_row = list_row
        layout.Add(list_row, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.all_countries = wx.CheckBox(self, label="Show servers from &all countries")
        set_accessible_name(self.all_countries, "Show servers from all countries, not just this one")
        layout.Add(self.all_countries, 0, wx.ALL, 8)

        # ... or a text box when it cannot (a custom command, or no VPN found).
        self.target_label = wx.StaticText(self, label="")
        layout.Add(self.target_label, 0, wx.ALL, 8)
        self.target = wx.ComboBox(self, choices=[], value=route.target if route else "")
        layout.Add(self.target, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.restore_label = wx.StaticText(self, label="&Disconnect command (optional):")
        layout.Add(self.restore_label, 0, wx.ALL, 8)
        self.restore = wx.TextCtrl(self, value=route.restore if route else "")
        set_accessible_name(self.restore, "Command that disconnects the VPN")
        layout.Add(self.restore, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.note = wx.StaticText(self, label="")
        layout.Add(self.note, 0, wx.ALL, 8)
        layout.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(layout)
        self.SetMinSize((500, -1))

        self._catalog: list[str] = []          # every server the VPN offers
        self._list_mode = False
        self._listed_country = route.country if route else ""
        self._initial = list(route.targets) if route else []
        self.method.Bind(wx.EVT_CHOICE, lambda e: self._refresh_method())
        self.country.Bind(wx.EVT_COMBOBOX, lambda e: self._country_changed())
        self.country.Bind(wx.EVT_TEXT, lambda e: self._country_changed())
        self.all_countries.Bind(wx.EVT_CHECKBOX, lambda e: self._fill_servers(self._checked()))
        self.up_btn.Bind(wx.EVT_BUTTON, lambda e: self._move(-1))
        self.down_btn.Bind(wx.EVT_BUTTON, lambda e: self._move(1))
        self.servers.Bind(wx.EVT_LISTBOX, lambda e: self._update_buttons())
        self.servers.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self._refresh_method()
        self.country.SetFocus()

    # -- what the method offers ------------------------------------------------------
    def _method(self) -> str:
        return METHODS[max(0, self.method.GetSelection())]

    def _refresh_method(self) -> None:
        method = self._method()
        label, name = _TARGET_HELP[method]
        self.target_label.SetLabel(label)
        set_accessible_name(self.target, name)
        custom = method == "command"
        self.restore_label.Show(custom)
        self.restore.Show(custom)
        changed = method != getattr(self, "_shown_method", method)
        keep_text = "" if changed else self.target.GetValue()
        self._shown_method = method
        if changed:
            self._initial = []
        self._catalog = (expressvpn_regions() if method == "expressvpn"
                         else tailscale_exit_nodes() if method == "tailscale" else [])
        self._list_mode = bool(self._catalog)
        if method == "expressvpn":
            self.note.SetLabel(
                "The first checked server is tried first. If a station still will not play, "
                "the next one is tried." if self._list_mode else
                "ExpressVPN was not found, so type regions separated by commas, for example "
                "uk-london, uk-manchester.")
        elif method == "tailscale":
            self.note.SetLabel(
                "Exit nodes on your tailnet. The first checked one is tried first." if self._list_mode else
                "No exit nodes were found. Turn one on in Tailscale, or type exit node names "
                "separated by commas.")
        else:
            self.note.SetLabel("Any VPN with command-line connect and disconnect commands.")
        self.target.SetValue(keep_text or ", ".join(self._initial))
        self.all_countries.Show(self._list_mode and method == "expressvpn")
        for widget in (self.servers_label, self.servers, self.up_btn, self.down_btn):
            widget.Show(self._list_mode)
        self.target_label.Show(not self._list_mode)
        self.target.Show(not self._list_mode)
        if self._list_mode:
            self._fill_servers(self._initial)
        self.Layout()
        self.Fit()

    # -- the checkable list ----------------------------------------------------------
    def _candidates(self) -> list[str]:
        if self._method() == "expressvpn" and not self.all_countries.GetValue():
            return regions_for_country(self._catalog, self.country.GetValue())
        return list(self._catalog)

    def _fill_servers(self, chosen: list[str]) -> None:
        """Show the chosen servers first, in order, then the rest of the candidates."""
        wanted = {name.lower() for name in chosen}
        items = arrange(self._candidates(), chosen)
        self.servers.Set(items)
        for index, name in enumerate(items):
            self.servers.Check(index, name.lower() in wanted)
        if items:
            self.servers.SetSelection(0)
        self._update_buttons()

    def _checked(self) -> list[str]:
        return [self.servers.GetString(i) for i in range(self.servers.GetCount()) if self.servers.IsChecked(i)]

    def _country_changed(self) -> None:
        """A different country shows that country's servers (and drops the old picks).
        Typing partial text changes nothing until it names a country with servers."""
        if not self._list_mode or self._method() != "expressvpn":
            return
        country = self.country.GetValue()
        if country == self._listed_country:
            return
        if self.all_countries.GetValue() or regions_for_country(self._catalog, country):
            self._listed_country = country
            self._fill_servers([])

    def _update_buttons(self) -> None:
        index = self.servers.GetSelection()
        count = self.servers.GetCount()
        self.up_btn.Enable(index not in (wx.NOT_FOUND, 0))
        self.down_btn.Enable(index != wx.NOT_FOUND and index < count - 1)

    def _move(self, delta: int) -> None:
        index = self.servers.GetSelection()
        if index == wx.NOT_FOUND:
            return
        items = [self.servers.GetString(i) for i in range(self.servers.GetCount())]
        checks = [self.servers.IsChecked(i) for i in range(len(items))]
        new_index = move(items, index, delta)
        if new_index == index:
            self._update_buttons()
            return
        checks[index], checks[new_index] = checks[new_index], checks[index]
        self.servers.Set(items)
        for i, state in enumerate(checks):
            self.servers.Check(i, state)
        self.servers.SetSelection(new_index)
        self._update_buttons()

    def _on_list_key(self, event) -> None:
        if event.AltDown() and event.GetKeyCode() in (wx.WXK_UP, wx.WXK_DOWN):
            self._move(-1 if event.GetKeyCode() == wx.WXK_UP else 1)
        else:
            event.Skip()

    # -- result ----------------------------------------------------------------------
    def _target_text(self) -> str:
        return ", ".join(self._checked()) if self._list_mode else self.target.GetValue().strip()

    def _on_ok(self, event) -> None:
        if not self.country.GetValue().strip() or not self._target_text():
            wx.MessageBox("Enter a country and " + ("check at least one server."
                          if self._list_mode else "what to connect to."),
                          "Route", wx.OK | wx.ICON_WARNING, self)
            return
        event.Skip()

    def route(self) -> Route:
        custom = self._method() == "command"
        return Route(self.country.GetValue().strip(), self._method(), self._target_text(),
                     self.restore.GetValue().strip() if custom else "")


class RoutesDialog(wx.Dialog):
    """List, add, edit and remove routes."""

    def __init__(self, parent, routes: list[Route]):
        super().__init__(parent, title="Regional Routes", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._routes = list(routes)
        self._countries = known_countries()
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(
            self, label="When a station from one of these countries needs it, your VPN is "
                        "switched as listed, then put back afterwards."), 0, wx.ALL, 8)
        layout.Add(wx.StaticText(self, label="&Routes:"), 0, wx.LEFT | wx.RIGHT, 8)
        self.list = wx.ListBox(self, size=(520, 160))
        set_accessible_name(self.list, "Routes: country and how it is reached")
        layout.Add(self.list, 1, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_btn = wx.Button(self, label="&Add...")
        self.edit_btn = wx.Button(self, label="&Edit...")
        self.remove_btn = wx.Button(self, label="&Remove")
        for button in (self.add_btn, self.edit_btn, self.remove_btn):
            row.Add(button, 0, wx.RIGHT, 6)
        layout.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        layout.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(layout)
        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.list.Bind(wx.EVT_LISTBOX, lambda e: self._buttons())
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_edit)
        self._fill()

    def routes(self) -> list[Route]:
        return list(self._routes)

    def _fill(self, select: int = 0) -> None:
        self.list.Set([f"{r.country}: {r.describe()}" for r in self._routes])
        if self._routes:
            self.list.SetSelection(min(select, len(self._routes) - 1))
        self._buttons()

    def _buttons(self) -> None:
        has = self.list.GetSelection() != wx.NOT_FOUND
        self.edit_btn.Enable(has)
        self.remove_btn.Enable(has)

    def _on_add(self, event) -> None:
        with RouteEditDialog(self, None, self._countries) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._replace(None, dialog.route())

    def _on_edit(self, event) -> None:
        index = self.list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        with RouteEditDialog(self, self._routes[index], self._countries) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._replace(index, dialog.route())

    def _replace(self, index: int | None, route: Route) -> None:
        """One route per country: a new one for a country replaces the old."""
        from radiomaster.services.routing import normalize_country
        key = normalize_country(route.country)
        kept = [r for i, r in enumerate(self._routes)
                if i != index and normalize_country(r.country) != key]
        position = min(index if index is not None else len(kept), len(kept))
        kept.insert(position, route)
        self._routes = kept
        self._fill(position)

    def _on_remove(self, event) -> None:
        index = self.list.GetSelection()
        if index != wx.NOT_FOUND:
            del self._routes[index]
            self._fill(index)
