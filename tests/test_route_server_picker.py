"""Edit Route: a checkable, orderable list of the chosen country's servers."""

import gc

import pytest
import wx

from radiomaster.services import vpn_regions as vr
from radiomaster.services.routing import Route
from radiomaster.ui import routing_dialog
from radiomaster.ui.routing_dialog import RouteEditDialog

UK = "United Kingdom Of Great Britain And Northern Ireland"
REGIONS = ["smart", "uk-london", "uk-east-london", "uk-manchester", "uk-docklands", "france-paris-1",
           "france-paris-2", "usa-new-york", "usa-boston", "south-korea-2", "turkey", "isle-of-man",
           "hong-kong-1", "india-(via-uk)", "gaming-europe"]


# --- which servers belong to a country ----------------------------------------------------

def test_a_country_lists_only_its_own_servers():
    assert vr.regions_for_country(REGIONS, UK) == ["uk-london", "uk-east-london", "uk-manchester", "uk-docklands"]
    assert vr.regions_for_country(REGIONS, "France") == ["france-paris-1", "france-paris-2"]
    assert vr.regions_for_country(REGIONS, "United States Of America") == ["usa-new-york", "usa-boston"]


def test_names_that_differ_between_the_catalog_and_the_vpn_still_match():
    assert vr.regions_for_country(REGIONS, "Republic Of Korea") == ["south-korea-2"]
    assert vr.regions_for_country(REGIONS, "Türkiye") == ["turkey"]
    assert vr.regions_for_country(REGIONS, "Hong Kong") == ["hong-kong-1"]
    assert vr.regions_for_country(REGIONS, "India") == ["india-(via-uk)"]      # not listed under the UK
    assert vr.regions_for_country(REGIONS, "Isle Of Man") == ["isle-of-man"]


def test_shortened_names_find_an_aliased_country():
    for typed in ("United Kingdom", "The United Kingdom", "UK"):
        assert len(vr.regions_for_country(REGIONS, typed)) == 4, typed
    assert vr.regions_for_country(REGIONS, "USA") == ["usa-new-york", "usa-boston"]
    assert vr.regions_for_country(REGIONS, "United") == []                     # too vague to guess
    assert vr.regions_for_country(REGIONS, "") == []


def test_entries_that_are_not_places_belong_to_no_country():
    assert not any(vr.region_matches_country(r, c) for r in ("smart", "gaming-europe") for c in (UK, "Europe"))


def test_chosen_servers_come_first_in_their_order_and_none_is_lost_or_repeated():
    shown = vr.arrange(["a", "b", "c", "d"], ["c", "x", "a"])
    assert shown == ["c", "x", "a", "b", "d"]                                  # "x" is kept though not a candidate
    assert vr.arrange(["A"], ["a"]) == ["a"]                                   # case-insensitive, no duplicate
    assert vr.arrange(["a", "b"], []) == ["a", "b"]


def test_moving_stops_at_the_ends():
    items = ["a", "b", "c"]
    assert vr.move(items, 1, -1) == 0 and items == ["b", "a", "c"]
    assert vr.move(items, 0, -1) == 0 and items == ["b", "a", "c"]
    assert vr.move(items, 2, 1) == 2 and items == ["b", "a", "c"]
    assert vr.move(items, 0, 1) == 1 and items == ["a", "b", "c"]


# --- the dialog -----------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    gc.collect()
    monkeypatch.setattr(routing_dialog, "expressvpn_regions", lambda: list(REGIONS))
    monkeypatch.setattr(routing_dialog, "tailscale_exit_nodes", lambda: ["pi-london", "pi-paris"])
    application = wx.App(False)
    yield application
    wx.Yield()


def names(dialog):
    return [dialog.servers.GetString(i) for i in range(dialog.servers.GetCount())]


def ticks(dialog):
    return [dialog.servers.IsChecked(i) for i in range(dialog.servers.GetCount())]


def test_a_new_route_lists_only_the_chosen_countrys_servers_unchecked(app):
    dialog = RouteEditDialog(None, None, [UK, "France"])
    dialog.country.SetValue(UK)
    dialog._country_changed()
    assert names(dialog) == ["uk-london", "uk-east-london", "uk-manchester", "uk-docklands"]
    assert ticks(dialog) == [False] * 4
    dialog.Destroy()


def test_check_servers_and_move_them_to_set_the_order(app):
    dialog = RouteEditDialog(None, None, [UK])
    dialog.country.SetValue(UK)
    dialog._country_changed()
    dialog.servers.Check(0, True)                       # uk-london
    dialog.servers.Check(2, True)                       # uk-manchester
    dialog.servers.SetSelection(2)
    dialog._move(-1)                                    # manchester above east-london
    dialog._move(-1)                                    # ... and above london
    assert names(dialog)[:3] == ["uk-manchester", "uk-london", "uk-east-london"]
    assert ticks(dialog)[:3] == [True, True, False]     # the ticks travel with their servers
    assert dialog.servers.GetSelection() == 0 and not dialog.up_btn.IsEnabled() and dialog.down_btn.IsEnabled()
    assert dialog.route() == Route(UK, "expressvpn", "uk-manchester, uk-london")
    dialog.servers.SetSelection(3)
    dialog._move(1)                                     # already last: nothing happens
    assert names(dialog)[3] == "uk-docklands" and not dialog.down_btn.IsEnabled()
    dialog.Destroy()


def test_moving_with_no_selection_does_nothing(app):
    dialog = RouteEditDialog(None, None, [UK])
    dialog.country.SetValue(UK)
    dialog._country_changed()
    dialog.servers.SetSelection(1)
    dialog._move(-1)
    assert names(dialog)[0] == "uk-east-london"
    dialog.Destroy()


def test_editing_a_route_shows_the_saved_servers_first_in_order(app):
    saved = Route(UK, "expressvpn", "uk-docklands, uk-london")
    dialog = RouteEditDialog(None, saved, [UK])
    assert names(dialog) == ["uk-docklands", "uk-london", "uk-east-london", "uk-manchester"]
    assert ticks(dialog) == [True, True, False, False]
    assert dialog.route() == saved
    dialog.Destroy()


def test_a_saved_server_from_another_country_is_kept_not_dropped(app):
    saved = Route(UK, "expressvpn", "uk-london, isle-of-man")
    dialog = RouteEditDialog(None, saved, [UK])
    assert "isle-of-man" in names(dialog) and dialog.route() == saved
    dialog.Destroy()


def test_changing_the_country_swaps_the_list_and_partial_typing_does_not(app):
    dialog = RouteEditDialog(None, Route(UK, "expressvpn", "uk-london"), [UK, "France"])
    dialog.country.SetValue("Fra")                      # still typing: nothing changes
    dialog._country_changed()
    assert names(dialog)[0] == "uk-london"
    dialog.country.SetValue("France")
    dialog._country_changed()
    assert names(dialog) == ["france-paris-1", "france-paris-2"] and ticks(dialog) == [False, False]
    dialog.Destroy()


def test_show_all_countries_lists_every_server(app):
    dialog = RouteEditDialog(None, None, [UK])
    dialog.country.SetValue(UK)
    dialog._country_changed()
    dialog.servers.Check(1, True)
    dialog.all_countries.SetValue(True)
    dialog._fill_servers(dialog._checked())
    assert len(names(dialog)) == len(REGIONS) and names(dialog)[0] == "uk-east-london"   # the pick stays on top
    assert dialog.route().target == "uk-east-london"
    dialog.Destroy()


def test_ok_needs_at_least_one_server_checked(app, monkeypatch):
    dialog = RouteEditDialog(None, None, [UK])
    dialog.country.SetValue(UK)
    dialog._country_changed()
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: shown.append(a[0]))
    event = type("E", (), {"Skip": lambda self: shown.append("accepted")})()
    dialog._on_ok(event)
    assert shown and "check at least one server" in shown[0]
    dialog.servers.Check(0, True)
    dialog._on_ok(event)
    assert shown[-1] == "accepted"
    dialog.Destroy()


def test_tailscale_lists_the_exit_nodes_on_the_tailnet(app):
    dialog = RouteEditDialog(None, Route(UK, "tailscale", "pi-paris"), [UK])
    assert dialog._list_mode and names(dialog) == ["pi-paris", "pi-london"]
    assert not dialog.all_countries.IsShown()           # exit nodes are not sorted by country
    dialog.servers.Check(1, True)
    assert dialog.route() == Route(UK, "tailscale", "pi-paris, pi-london")
    dialog.Destroy()


def test_without_the_vpn_installed_a_text_box_is_used(app, monkeypatch):
    monkeypatch.setattr(routing_dialog, "expressvpn_regions", lambda: [])
    dialog = RouteEditDialog(None, Route(UK, "expressvpn", "uk-london, uk-manchester"), [UK])
    assert not dialog._list_mode and dialog.target.IsShown() and not dialog.servers.IsShown()
    assert dialog.route() == Route(UK, "expressvpn", "uk-london, uk-manchester")
    assert "not found" in dialog.note.GetLabel()
    dialog.Destroy()


def test_custom_commands_use_the_text_boxes_not_the_list(app):
    dialog = RouteEditDialog(None, Route(UK, "command", "vpn connect uk", "vpn disconnect"), [UK])
    assert not dialog._list_mode and dialog.restore.IsShown()
    assert dialog.route() == Route(UK, "command", "vpn connect uk", "vpn disconnect")
    dialog.Destroy()
