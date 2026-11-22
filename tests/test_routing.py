"""Regional routing: country rules, the VPN backends, restore, and the radio hooks."""

import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from radiomaster.services import routing
from radiomaster.services.routing import (
    CommandBackend, ExpressVpnBackend, Route, RouteError, RoutingManager, TailscaleBackend,
    normalize_country)


class Config:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def script(responses):
    """A fake command runner: matches on the arguments after the program name."""
    calls = []

    def run(args, timeout=20.0):
        calls.append(args[1:])
        for prefix, answer in responses:
            if args[1:1 + len(prefix)] == list(prefix):
                return answer if callable(answer) is False else answer()
        return 0, ""
    run.calls = calls
    return run


def express(run):
    return ExpressVpnBackend(run=run, sleep=lambda _s: None, exe="expressvpnctl")


# --- rules ---------------------------------------------------------------------

def test_countries_match_however_the_catalog_spells_them():
    assert normalize_country("The United Kingdom Of Great Britain And Northern Ireland") == \
        normalize_country("  united kingdom of great britain and northern ireland ")
    assert normalize_country("") == ""


def test_route_for_needs_the_feature_on_and_a_rule_for_that_country():
    routes = [{"country": "United Kingdom", "method": "expressvpn", "target": "uk-london"},
              {"country": "Broken", "method": "nonsense", "target": "x"},
              {"country": "", "method": "expressvpn", "target": "x"}]
    off = RoutingManager(Config(**{"routing.routes": routes}), backends={})
    assert off.route_for("United Kingdom") is None
    on = RoutingManager(Config(**{"routing.enabled": True, "routing.routes": routes}), backends={})
    assert on.route_for("The United Kingdom").target == "uk-london"
    assert on.route_for("France") is None
    assert len(on.routes()) == 1                    # invalid rules are ignored


def test_mode_defaults_to_only_when_blocked():
    assert RoutingManager(Config(), backends={}).mode == "when_blocked"
    assert RoutingManager(Config(**{"routing.mode": "always"}), backends={}).mode == "always"
    assert RoutingManager(Config(**{"routing.mode": "bogus"}), backends={}).mode == "when_blocked"


# --- ExpressVPN ----------------------------------------------------------------

def test_expressvpn_connects_to_the_region_and_waits_for_it():
    states = iter(["Disconnected", "Connecting", "Connected"])
    run = script([(("get", "connectionstate"), lambda: (0, next(states))),
                  (("get", "dnsconfigured"), (0, "true")),
                  (("get", "region"), (0, "france-paris-1"))])
    # snapshot() reads the state once, apply() reads it again, then waiting polls it
    backend = express(run)
    backend.apply(Route("United Kingdom", "expressvpn", "uk-london"))
    assert ["connect", "uk-london"] in run.calls


def test_expressvpn_already_in_the_region_does_nothing():
    run = script([(("get", "connectionstate"), (0, "Connected")),
                  (("get", "region"), (0, "uk-london"))])
    express(run).apply(Route("United Kingdom", "expressvpn", "uk-london"))
    assert not any(call[:1] == ["connect"] for call in run.calls)


def test_expressvpn_restore_reconnects_to_the_old_region_or_disconnects():
    run = script([(("get", "connectionstate"), (0, "Connected")),
                  (("get", "dnsconfigured"), (0, "true"))])
    express(run).restore({"state": "Connected", "region": "uk-london"})
    assert ["connect", "uk-london"] in run.calls
    run = script([])
    express(run).restore({"state": "Disconnected", "region": "uk-london"})
    assert ["disconnect"] in run.calls
    assert ["set", "region", "uk-london"] in run.calls      # the selected region goes back too


def test_a_failing_vpn_command_is_reported_not_raised_raw():
    run = script([(("get", "connectionstate"), (1, "Daemon not running"))])
    with pytest.raises(RouteError, match="Daemon not running"):
        express(run).snapshot()


def test_missing_vpn_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(routing, "find_expressvpn", lambda: None)
    with pytest.raises(RouteError, match="not installed"):
        ExpressVpnBackend(run=script([])).snapshot()


# --- Tailscale -----------------------------------------------------------------

def test_tailscale_sets_the_exit_node_and_restores_the_previous_one():
    status = {"ExitNodeStatus": {"Online": True, "TailscaleIPs": ["100.1.2.3/32"]}}
    run = script([(("status", "--json"), (0, json.dumps(status)))])
    backend = TailscaleBackend(run=run, sleep=lambda _s: None, exe="tailscale")
    assert backend.snapshot() == {"exit_node": "100.1.2.3"}
    backend.apply(Route("United Kingdom", "tailscale", "uk-pi"))
    backend.restore({"exit_node": "100.1.2.3"})
    backend.restore({"exit_node": ""})
    assert ["set", "--exit-node=uk-pi"] in run.calls
    assert ["set", "--exit-node=100.1.2.3"] in run.calls
    assert ["set", "--exit-node="] in run.calls


def test_tailscale_exit_node_that_never_comes_online_is_an_error(monkeypatch):
    monkeypatch.setattr(routing, "CONNECT_TIMEOUT_SECONDS", 0.05)
    run = script([(("status", "--json"), (0, json.dumps({})))])
    backend = TailscaleBackend(run=run, sleep=lambda _s: None, exe="tailscale")
    with pytest.raises(RouteError, match="did not come online"):
        backend.apply(Route("United Kingdom", "tailscale", "uk-pi"))


# --- custom commands -----------------------------------------------------------

def test_custom_commands_run_connect_then_disconnect():
    run = script([])
    backend = CommandBackend(run=run)
    route = Route("United Kingdom", "command", 'vpn.exe connect "uk london"', "vpn.exe disconnect")
    backend.apply(route)
    backend.restore_with(route)
    assert run.calls == [['connect', 'uk london'], ['disconnect']]


def test_custom_command_failure_is_reported():
    backend = CommandBackend(run=script([((), (2, "no such location"))]))
    with pytest.raises(RouteError, match="no such location"):
        backend.apply(Route("X", "command", "vpn connect x"))


# --- manager -------------------------------------------------------------------

class FakeBackend:
    def __init__(self):
        self.applied, self.restored = [], []

    def snapshot(self):
        return {"before": True}

    def apply(self, route):
        self.applied.append(route)

    def restore(self, snapshot):
        self.restored.append(snapshot)


def manager_with(backend, schedule=None, **extra):
    config = Config(**{"routing.enabled": True, "routing.routes": [
        {"country": "United Kingdom", "method": "expressvpn", "target": "uk-london"},
        {"country": "France", "method": "expressvpn", "target": "france-paris-1"},
    ], **extra})
    return RoutingManager(config, backends={"expressvpn": backend}, schedule=schedule)


def test_prepare_applies_once_and_release_restores_the_original_state():
    backend = FakeBackend()
    manager = manager_with(backend)
    assert manager.prepare("United Kingdom").target == "uk-london"
    manager.prepare("The United Kingdom")                 # same route: nothing more to do
    assert len(backend.applied) == 1
    manager.release()
    assert backend.restored == [{"before": True}] and manager.active is None
    manager.release()                                     # nothing left to restore
    assert len(backend.restored) == 1


def test_switching_countries_keeps_the_very_first_state_to_restore():
    backend = FakeBackend()
    manager = manager_with(backend)
    manager.prepare("United Kingdom")
    backend.snapshot = lambda: {"before": False}          # the VPN is now pointed at the UK
    manager.prepare("France")
    manager.release()
    assert backend.restored == [{"before": True}]


def test_country_without_a_route_changes_nothing():
    backend = FakeBackend()
    assert manager_with(backend).prepare("Germany") is None
    assert backend.applied == []


def test_release_later_waits_and_a_new_route_cancels_it():
    backend = FakeBackend()
    timers = []

    def schedule(delay, action):
        timer = SimpleNamespace(delay=delay, action=action, cancel=MagicMock())
        timers.append(timer)
        return timer

    manager = manager_with(backend, schedule=schedule)
    manager.release_later()                               # nothing applied yet: no timer
    assert timers == []
    manager.prepare("United Kingdom")
    manager.release_later(20)
    assert timers[0].delay == 20 and backend.restored == []
    manager.prepare("France")                             # playing something routed again
    timers[0].cancel.assert_called_once()
    timers.clear()
    manager.release_later(20)
    timers[0].action()
    assert backend.restored and manager.active is None


def test_failed_apply_leaves_nothing_applied():
    backend = FakeBackend()
    backend.apply = MagicMock(side_effect=RouteError("no"))
    manager = manager_with(backend)
    with pytest.raises(RouteError):
        manager.prepare("United Kingdom")
    assert manager.active is None


# --- radio panel hooks ---------------------------------------------------------

def radio_panel_stub(manager, station):
    from radiomaster.ui.radio_panel import RadioPanel
    panel = SimpleNamespace(
        _playing_station=station, _region_retry_url=None, engine=MagicMock(),
        _routing_status=MagicMock())
    panel._retry_through_route = lambda s, r, advance=False: RadioPanel._retry_through_route(panel, s, r, advance)
    return RadioPanel, panel


def station(country="United Kingdom"):
    return SimpleNamespace(name="BBC", url="https://bbc.test/live", country=country,
                           is_live=True, uuid="u")


def test_always_mode_routes_before_playing(monkeypatch):
    backend = FakeBackend()
    manager = manager_with(backend, **{"routing.mode": "always"})
    monkeypatch.setattr(routing, "_manager", manager)
    RadioPanel, panel = radio_panel_stub(manager, station())
    play = MagicMock()
    RadioPanel._route_then_play(panel, station(), play, title="BBC")
    assert len(backend.applied) == 1
    play.assert_called_once_with("https://bbc.test/live", title="BBC")


def test_when_blocked_mode_plays_directly_first(monkeypatch):
    backend = FakeBackend()
    manager = manager_with(backend)                       # default mode
    monkeypatch.setattr(routing, "_manager", manager)
    RadioPanel, panel = radio_panel_stub(manager, station())
    play = MagicMock()
    RadioPanel._route_then_play(panel, station(), play, title="BBC")
    assert backend.applied == []
    play.assert_called_once()


def test_playback_still_starts_when_the_route_fails(monkeypatch):
    backend = FakeBackend()
    backend.apply = MagicMock(side_effect=RouteError("VPN is off"))
    manager = manager_with(backend, **{"routing.mode": "always"})
    monkeypatch.setattr(routing, "_manager", manager)
    RadioPanel, panel = radio_panel_stub(manager, station())
    play = MagicMock()
    RadioPanel._route_then_play(panel, station(), play, title="BBC")
    play.assert_called_once()
    assert "VPN is off" in panel._routing_status.call_args.args[0]


def test_blocked_station_is_routed_and_retried_once(monkeypatch):
    backend = FakeBackend()
    manager = manager_with(backend)
    monkeypatch.setattr(routing, "_manager", manager)
    uk = station()
    RadioPanel, panel = radio_panel_stub(manager, uk)
    started = []
    monkeypatch.setattr("radiomaster.ui.radio_panel.threading.Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: started.append((target, args))))
    assert RadioPanel._handle_region_blocked(panel, uk.url) is True
    target, args = started[0]
    target(*args)
    assert len(backend.applied) == 1
    panel.engine.play.assert_called_once()
    assert RadioPanel._handle_region_blocked(panel, uk.url) is False   # only one retry


def test_blocked_station_without_a_route_shows_the_normal_message(monkeypatch):
    manager = manager_with(FakeBackend())
    monkeypatch.setattr(routing, "_manager", manager)
    de = station("Germany")
    RadioPanel, panel = radio_panel_stub(manager, de)
    assert RadioPanel._handle_region_blocked(panel, de.url) is False


def test_engine_hands_a_region_block_to_the_routing_hook(monkeypatch):
    from radiomaster.engine.playback_engine import PlaybackEngine
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: 403)
    hook = MagicMock(return_value=True)
    engine = SimpleNamespace(_playback_generation=1, _notify_error=MagicMock(), _on_region_blocked=hook)
    PlaybackEngine._explain_open_failure(engine, 1, "https://x/live", "BASS error 2")
    hook.assert_called_once_with("https://x/live")
    engine._notify_error.assert_not_called()           # the retry is underway, no error dialog
    hook.return_value = False
    PlaybackEngine._explain_open_failure(engine, 1, "https://x/live", "BASS error 2")
    assert "licensed only for listeners" in engine._notify_error.call_args.args[0]


def test_expressvpn_waits_for_dns_after_it_reports_connected():
    dns = iter(["false", "false", "true"])
    run = script([(("get", "connectionstate"), (0, "Connected")),
                  (("get", "region"), (0, "france-paris-1")),
                  (("get", "dnsconfigured"), lambda: (0, next(dns)))])
    express(run).apply(Route("United Kingdom", "expressvpn", "uk-london"))
    assert sum(call == ["get", "dnsconfigured"] for call in run.calls) == 3


def test_older_expressvpn_without_the_dns_flag_still_connects():
    run = script([(("get", "connectionstate"), (0, "Connected")),
                  (("get", "region"), (0, "france-paris-1")),
                  (("get", "dnsconfigured"), (1, "unknown command"))])
    express(run).apply(Route("United Kingdom", "expressvpn", "uk-london"))
    assert ["connect", "uk-london"] in run.calls


# --- several servers per route -----------------------------------------------------------

def uk_route(target):
    return {"country": "United Kingdom", "method": "expressvpn", "target": target}


def test_a_route_lists_its_servers_in_order():
    assert Route("UK", "expressvpn", "uk-london, uk-manchester;uk-docklands").targets == (
        "uk-london", "uk-manchester", "uk-docklands")
    assert Route("UK", "tailscale", "pi-1,pi-2").targets == ("pi-1", "pi-2")
    assert Route("UK", "command", "vpn connect uk, now").targets == ("vpn connect uk, now",)
    assert Route.from_dict({"country": "UK", "method": "expressvpn", "target": " , "}) is None


def test_connects_the_first_server_and_advances_to_the_next_when_asked():
    backend = FakeBackend()
    manager = manager_with(backend)
    manager._config.values["routing.routes"] = [uk_route("uk-london, uk-manchester, uk-docklands")]
    manager.prepare("United Kingdom")
    assert [r.target for r in backend.applied] == ["uk-london"]
    assert manager.server == "uk-london" and manager.can_advance()
    assert manager.advance() == "uk-manchester" and manager.server == "uk-manchester"
    assert manager.advance() == "uk-docklands" and not manager.can_advance()
    assert manager.advance() is None
    assert [r.target for r in backend.applied] == ["uk-london", "uk-manchester", "uk-docklands"]
    manager.prepare("United Kingdom")                   # same route: stays on the working server
    assert len(backend.applied) == 3
    manager.release()
    assert backend.restored == [{"before": True}]       # restores the state before the FIRST server
    assert manager.server == "" and manager.advance() is None


def test_a_single_server_route_has_nothing_to_advance_to():
    backend = FakeBackend()
    manager = manager_with(backend)
    manager.prepare("United Kingdom")
    assert not manager.can_advance() and manager.advance() is None


def test_a_failed_switch_to_the_next_server_is_reported_and_keeps_the_current_one():
    backend = FakeBackend()
    manager = manager_with(backend)
    manager._config.values["routing.routes"] = [uk_route("uk-london, uk-manchester")]
    manager.prepare("United Kingdom")
    backend.apply = MagicMock(side_effect=RouteError("no"))
    with pytest.raises(RouteError):
        manager.advance()
    assert manager.server == "uk-london"


def test_still_blocked_through_the_connected_server_tries_the_next_one(monkeypatch):
    backend = FakeBackend()
    manager = manager_with(backend)
    manager._config.values["routing.routes"] = [uk_route("uk-london, uk-manchester")]
    monkeypatch.setattr(routing, "_manager", manager)
    uk = station()
    RadioPanel, panel = radio_panel_stub(manager, uk)
    started = []
    monkeypatch.setattr("radiomaster.ui.radio_panel.threading.Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: started.append((target, args))))
    assert RadioPanel._handle_region_blocked(panel, uk.url) is True        # refused: connect London
    target, args = started.pop()
    target(*args)
    assert manager.server == "uk-london" and panel.engine.play.call_count == 1
    assert RadioPanel._handle_region_blocked(panel, uk.url) is True        # still refused: next server
    target, args = started.pop()
    target(*args)
    assert manager.server == "uk-manchester" and panel.engine.play.call_count == 2
    assert RadioPanel._handle_region_blocked(panel, uk.url) is False       # nothing left to try
