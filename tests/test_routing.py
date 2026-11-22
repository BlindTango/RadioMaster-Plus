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
        _routing_status=MagicMock(),
        _watch_routed_start=MagicMock(), ROUTED_START_TIMEOUT=0.2)
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
    assert isinstance(RadioPanel._handle_region_blocked(panel, uk.url), str)   # only one retry


def test_blocked_station_without_a_route_shows_the_normal_message(monkeypatch):
    manager = manager_with(FakeBackend())
    monkeypatch.setattr(routing, "_manager", manager)
    de = station("Germany")
    RadioPanel, panel = radio_panel_stub(manager, de)
    note = RadioPanel._handle_region_blocked(panel, de.url)
    assert isinstance(note, str) and "no route for Germany" in note


def test_engine_hands_a_region_block_to_the_routing_hook(monkeypatch):
    from radiomaster.engine.playback_engine import PlaybackEngine
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: 403)
    hook = MagicMock(return_value=True)
    engine = SimpleNamespace(_playback_generation=1, _notify_error=MagicMock(), _on_region_blocked=hook, _on_open_failed=None)
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
    assert isinstance(RadioPanel._handle_region_blocked(panel, uk.url), str)   # nothing left to try


# --- a server that reaches the broadcaster but cannot carry the audio -----------------------

def routed_panel(monkeypatch, servers="uk-london, uk-manchester"):
    backend = FakeBackend()
    manager = manager_with(backend)
    manager._config.values["routing.routes"] = [uk_route(servers)]
    monkeypatch.setattr(routing, "_manager", manager)
    uk = station()
    RadioPanel, panel = radio_panel_stub(manager, uk)
    manager.prepare(uk.country)
    return RadioPanel, panel, manager, uk


def test_station_stuck_at_buffering_moves_to_the_next_server(monkeypatch):
    RadioPanel, panel, manager, uk = routed_panel(monkeypatch)
    panel.engine.state = "buffering"
    panel._retry_through_route = MagicMock()
    RadioPanel._watch_routed_start(panel, uk, manager.active)
    panel._retry_through_route.assert_called_once_with(uk, manager.active, True)
    assert "did not start through uk-london" in panel._routing_status.call_args.args[0]


def test_a_station_that_starts_playing_is_left_alone(monkeypatch):
    RadioPanel, panel, manager, uk = routed_panel(monkeypatch)
    panel.engine.state = "playing"
    panel._retry_through_route = MagicMock()
    RadioPanel._watch_routed_start(panel, uk, manager.active)
    panel._retry_through_route.assert_not_called()


def test_no_other_server_means_no_retry_and_a_chosen_other_station_cancels_the_watch(monkeypatch):
    RadioPanel, panel, manager, uk = routed_panel(monkeypatch, servers="uk-london")
    panel.engine.state = "buffering"
    panel._retry_through_route = MagicMock()
    RadioPanel._watch_routed_start(panel, uk, manager.active)           # nothing to advance to
    panel._playing_station = station("France")
    RadioPanel._watch_routed_start(panel, uk, manager.active)           # listener moved on
    panel._retry_through_route.assert_not_called()


def test_a_failed_open_through_a_connected_server_tries_the_next(monkeypatch):
    RadioPanel, panel, manager, uk = routed_panel(monkeypatch)
    started = []
    monkeypatch.setattr("radiomaster.ui.radio_panel.threading.Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: started.append(args)))
    assert RadioPanel._handle_open_failed(panel, uk.url) is True
    assert started == [(uk, manager.active, True)]
    manager.advance()                                                   # now on the last server
    assert RadioPanel._handle_open_failed(panel, uk.url) is False


def test_a_failed_open_without_routing_shows_the_normal_error(monkeypatch):
    manager = manager_with(FakeBackend())
    monkeypatch.setattr(routing, "_manager", manager)
    uk = station()
    RadioPanel, panel = radio_panel_stub(manager, uk)
    assert RadioPanel._handle_open_failed(panel, uk.url) is False       # no route connected
    assert RadioPanel._handle_open_failed(panel, "https://other") is False


def test_engine_sends_a_non_region_failure_to_the_open_failed_hook(monkeypatch):
    from radiomaster.engine.playback_engine import PlaybackEngine
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: None)
    hook = MagicMock(return_value=True)
    engine = SimpleNamespace(_playback_generation=1, _notify_error=MagicMock(),
                             _on_region_blocked=MagicMock(), _on_open_failed=hook)
    PlaybackEngine._explain_open_failure(engine, 1, "https://x/live", "BASS error 2")
    hook.assert_called_once_with("https://x/live")
    engine._on_region_blocked.assert_not_called()
    engine._notify_error.assert_not_called()
    hook.return_value = False
    PlaybackEngine._explain_open_failure(engine, 1, "https://x/live", "BASS error 2")
    engine._notify_error.assert_called_once_with("BASS error 2")


# --- telling the listener why routing could not help ------------------------------------------

def test_last_server_still_refused_says_so(monkeypatch):
    RadioPanel, panel, manager, uk = routed_panel(monkeypatch, servers="uk-london")
    note = RadioPanel._handle_region_blocked(panel, uk.url)
    assert isinstance(note, str) and "uk-london" in note and "last server" in note


def test_a_vpn_that_could_not_be_switched_is_named_in_the_message(monkeypatch):
    backend = FakeBackend()
    backend.apply = MagicMock(side_effect=RouteError("ExpressVPN: the app is not running"))
    manager = manager_with(backend)
    monkeypatch.setattr(routing, "_manager", manager)
    uk = station()
    RadioPanel, panel = radio_panel_stub(manager, uk)
    with pytest.raises(RouteError):
        manager.prepare(uk.country)
    assert manager.last_error == "ExpressVPN: the app is not running"
    panel._region_retry_url = uk.url                   # the retry already happened once
    note = RadioPanel._handle_region_blocked(panel, uk.url)
    assert isinstance(note, str) and "the app is not running" in note


def test_a_station_without_a_country_explains_why_it_was_not_routed(monkeypatch):
    manager = manager_with(FakeBackend())
    monkeypatch.setattr(routing, "_manager", manager)
    nowhere = station("")
    RadioPanel, panel = radio_panel_stub(manager, nowhere)
    note = RadioPanel._handle_region_blocked(panel, nowhere.url)
    assert isinstance(note, str) and "no country" in note


def test_engine_adds_the_routing_note_to_the_region_message(monkeypatch):
    from radiomaster.engine.playback_engine import PlaybackEngine
    monkeypatch.setattr("radiomaster.services.region_block.region_block_status", lambda url: 403)
    engine = SimpleNamespace(_playback_generation=1, _notify_error=MagicMock(),
                             _on_region_blocked=lambda url: "Routing could not switch your VPN: off.",
                             _on_open_failed=None)
    PlaybackEngine._explain_open_failure(engine, 1, "https://x/live", "BASS error 2")
    shown = engine._notify_error.call_args.args[0]
    assert "refused the connection (HTTP 403)" in shown and shown.endswith("could not switch your VPN: off.")


def test_expressvpn_region_names_are_lowercased_and_a_bad_server_is_skipped():
    assert Route("UK", "expressvpn", "uk-east-London, UK-Wembley").targets == ("uk-east-london", "uk-wembley")
    assert Route("UK", "tailscale", "Pi-1").targets == ("Pi-1",)             # exit node names keep their case
    backend = FakeBackend()
    manager = manager_with(backend)
    manager._config.values["routing.routes"] = [uk_route("uk-london, uk-bogus, uk-manchester")]
    manager.prepare("United Kingdom")
    real_apply = backend.apply
    backend.apply = lambda route: (_ for _ in ()).throw(RouteError("unknown region"))         if route.target == "uk-bogus" else real_apply(route)
    assert manager.advance() == "uk-manchester"                              # skipped the bad one
    assert manager.server == "uk-manchester" and not manager.can_advance()


# --- the VPN must not be put back while a station is playing ---------------------------------

def timers_for(manager):
    timers = []

    def schedule(delay, action):
        timer = SimpleNamespace(delay=delay, action=action, cancel=MagicMock())
        timers.append(timer)
        return timer

    manager._schedule = schedule
    return timers


def test_a_stop_at_the_start_of_play_does_not_release_the_vpn_while_playing():
    backend = FakeBackend()
    manager = manager_with(backend)
    timers = timers_for(manager)
    manager.prepare("United Kingdom")
    # the player reports "stopped" first (it stops the old station), then plays
    routing.follow_playback(manager, "stopped", lambda: False)
    assert len(timers) == 1
    routing.follow_playback(manager, "buffering", lambda: True)
    timers[0].cancel.assert_called_once()                 # the pending restore is cancelled
    routing.follow_playback(manager, "playing", lambda: True)
    assert backend.restored == []


def test_a_restore_that_fires_while_something_still_plays_leaves_the_vpn_connected():
    backend = FakeBackend()
    manager = manager_with(backend)
    timers = timers_for(manager)
    manager.prepare("United Kingdom")
    routing.follow_playback(manager, "stopped", lambda: True)   # never cancelled, but playing
    timers[0].action()
    assert backend.restored == [] and manager.active is not None


def test_the_vpn_is_put_back_after_playback_really_stops():
    backend = FakeBackend()
    manager = manager_with(backend)
    timers = timers_for(manager)
    manager.prepare("United Kingdom")
    routing.follow_playback(manager, "playing", lambda: True)
    routing.follow_playback(manager, "stopped", lambda: False)
    timers[-1].action()
    assert backend.restored == [{"before": True}] and manager.active is None
    routing.follow_playback(manager, "paused", lambda: True)    # other states change nothing
