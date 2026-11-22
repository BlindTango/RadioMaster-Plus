"""Edit the country routes used by Regional routing (Settings > Network)."""

from __future__ import annotations

import wx

from radiomaster.services.routing import (
    METHOD_LABELS, METHODS, Route, find_expressvpn, run_command)
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
    return [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []


class RouteEditDialog(wx.Dialog):
    def __init__(self, parent, route: Route | None = None, countries: list[str] | None = None):
        super().__init__(parent, title="Edit Route" if route else "Add Route")
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
        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizerAndFit(layout)
        self.SetMinSize((460, -1))
        self.method.Bind(wx.EVT_CHOICE, lambda e: self._refresh_target())
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self._refresh_target()
        self.country.SetFocus()

    def _method(self) -> str:
        return METHODS[max(0, self.method.GetSelection())]

    def _refresh_target(self) -> None:
        method = self._method()
        label, name = _TARGET_HELP[method]
        self.target_label.SetLabel(label)
        set_accessible_name(self.target, name)
        custom = method == "command"
        self.restore_label.Show(custom)
        self.restore.Show(custom)
        # Keep what is typed while the same method is showing (editing a route);
        # a different method starts from an empty box.
        keep = self.target.GetValue() if method == getattr(self, "_shown_method", method) else ""
        self._shown_method = method
        self.target.Clear()
        if method == "expressvpn":
            regions = expressvpn_regions()
            self.target.Set(regions)
            self.note.SetLabel(
                "List several regions to have the next one tried when a station still will not "
                "play, for example uk-london, uk-manchester, uk-docklands."
                + ("" if regions else " ExpressVPN was not found; you can still type regions."))
        elif method == "tailscale":
            self.note.SetLabel("Exit nodes must already be set up in Tailscale for your account. "
                               "List several to have the next one tried if a station still will not play.")
        else:
            self.note.SetLabel("Any VPN with command-line connect and disconnect commands.")
        self.target.SetValue(keep)
        self.Layout()
        self.Fit()

    def _on_ok(self, event) -> None:
        if not self.country.GetValue().strip() or not self.target.GetValue().strip():
            wx.MessageBox("Enter a country and what to connect to.", "Route", wx.OK | wx.ICON_WARNING, self)
            return
        event.Skip()

    def route(self) -> Route:
        custom = self._method() == "command"
        return Route(self.country.GetValue().strip(), self._method(), self.target.GetValue().strip(),
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
