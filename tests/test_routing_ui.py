"""Regional routing screens: the routes list, the edit dialog and the Network settings."""

import gc

import pytest
import wx

from radiomaster.services.routing import Route
from radiomaster.ui import routing_dialog
from radiomaster.ui.routing_dialog import RouteEditDialog, RoutesDialog


@pytest.fixture
def app(monkeypatch):
    gc.collect()
    monkeypatch.setattr(routing_dialog, "expressvpn_regions", lambda: ["uk-london", "france-paris-1"])
    monkeypatch.setattr(routing_dialog, "known_countries", lambda: ["France", "United Kingdom"])
    application = wx.App(False)
    yield application
    wx.Yield()


def test_edit_dialog_builds_a_route_for_each_method(app, monkeypatch):
    monkeypatch.setattr(routing_dialog, "tailscale_exit_nodes", lambda: [])    # none found: a text box
    dialog = RouteEditDialog(None, None, ["United Kingdom"])
    dialog.country.SetValue("United Kingdom")
    dialog._country_changed()
    dialog.servers.Check(0, True)                              # ExpressVPN: tick a listed server
    assert dialog.route() == Route("United Kingdom", "expressvpn", "uk-london")
    dialog.method.SetSelection(2)
    dialog._refresh_method()
    dialog.target.SetValue("vpn connect uk")
    dialog.restore.SetValue("vpn disconnect")
    assert dialog.route() == Route("United Kingdom", "command", "vpn connect uk", "vpn disconnect")
    assert dialog.restore.IsShown()
    dialog.method.SetSelection(1)                              # Tailscale with no nodes found: a text box
    dialog._refresh_method()
    dialog.target.SetValue("pi-1, pi-2")
    assert not dialog.restore.IsShown()
    assert dialog.route() == Route("United Kingdom", "tailscale", "pi-1, pi-2")   # only custom keeps a disconnect
    dialog.Destroy()


def test_edit_dialog_shows_an_existing_route(app, monkeypatch):
    monkeypatch.setattr(routing_dialog, "tailscale_exit_nodes", lambda: [])
    existing = Route("France", "tailscale", "paris-pi")
    dialog = RouteEditDialog(None, existing, ["France"])
    assert dialog.route() == existing
    dialog.Destroy()


def test_routes_dialog_lists_adds_replaces_and_removes(app):
    uk = Route("United Kingdom", "expressvpn", "uk-london")
    dialog = RoutesDialog(None, [uk])
    assert dialog.list.GetStrings() == ["United Kingdom: ExpressVPN: uk-london"]
    assert dialog.edit_btn.IsEnabled() and dialog.remove_btn.IsEnabled()
    dialog._replace(None, Route("France", "expressvpn", "france-paris-1"))
    assert [r.country for r in dialog.routes()] == ["United Kingdom", "France"]
    dialog._replace(None, Route("The United Kingdom", "tailscale", "uk-pi"))   # same country
    assert [r.country for r in dialog.routes()] == ["France", "The United Kingdom"]
    dialog.list.SetSelection(0)
    dialog._on_remove(None)
    assert [r.country for r in dialog.routes()] == ["The United Kingdom"]
    dialog._on_remove(None)
    assert dialog.routes() == [] and not dialog.remove_btn.IsEnabled()
    dialog.Destroy()


def test_network_settings_save_and_reload_the_routing_choices(app, tmp_path, monkeypatch):
    from radiomaster.ui.settings_dialog import NetworkPanel
    from radiomaster.utils.config import ConfigManager
    config = ConfigManager(str(tmp_path))
    monkeypatch.setattr(ConfigManager, "_instance", config)
    frame = wx.Frame(None)
    panel = NetworkPanel(frame, config)
    assert not panel.routing_chk.IsChecked() and not panel.routes_btn.IsEnabled()
    panel.routing_chk.SetValue(True)
    panel._update_routing_states()
    assert panel.routes_btn.IsEnabled() and panel.routing_mode.IsEnabled()
    panel.routing_mode.SetSelection(1)
    panel._routes = [Route("United Kingdom", "expressvpn", "uk-london")]
    panel.onSave()
    assert config.get("routing.enabled") is True
    assert config.get("routing.mode") == "always"
    assert config.get("routing.routes") == [
        {"country": "United Kingdom", "method": "expressvpn", "target": "uk-london", "restore": ""}]
    reopened = NetworkPanel(frame, config)
    assert reopened.routing_chk.IsChecked() and reopened.routing_mode.GetSelection() == 1
    frame.Destroy()
