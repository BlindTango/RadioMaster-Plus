"""Regional routing: reach a station through a VPN in the station's own country.

Many stations are licensed only for listeners in their home country. This
drives a VPN the person already has (ExpressVPN, Tailscale with an exit node in
that country, or any VPN with command-line connect and disconnect commands) so
it points at the station's country while the station plays, then puts the VPN
back the way it was. RadioMaster+ supplies no VPN or servers of its own.

A VPN changes the route for the whole computer, not for one program, so the
previous state is restored shortly after playback stops and when the program
exits.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

log = logging.getLogger("radiomaster")

METHODS = ("expressvpn", "tailscale", "command")
METHOD_LABELS = {
    "expressvpn": "ExpressVPN",
    "tailscale": "Tailscale exit node",
    "command": "Custom commands",
}
MODE_ALWAYS = "always"
MODE_WHEN_BLOCKED = "when_blocked"
RESTORE_DELAY_SECONDS = 20.0
CONNECT_TIMEOUT_SECONDS = 60.0
SETTLE_SECONDS = 4.0


class RouteError(Exception):
    """A route could not be set up; the message is safe to show to the listener."""


def normalize_country(name: str) -> str:
    """Country names compared the same way however the catalog spells them."""
    text = " ".join((name or "").casefold().split())
    return text[4:] if text.startswith("the ") else text


@dataclass(frozen=True)
class Route:
    country: str
    method: str
    target: str = ""          # ExpressVPN region(s), Tailscale exit node(s), or connect command
    restore: str = ""         # custom command only: the disconnect command

    @property
    def targets(self) -> tuple[str, ...]:
        """The servers to try, in order. ExpressVPN regions and Tailscale exit nodes
        may be listed with commas: one server can be blocked by a broadcaster while
        another in the same country plays."""
        if self.method == "command":
            return (self.target,)
        return tuple(part.strip() for part in re.split(r"[,;\n]", self.target) if part.strip())

    def single(self, server: str) -> "Route":
        """This route pointed at just one of its servers."""
        return replace(self, target=server)

    def to_dict(self) -> dict:
        return {"country": self.country, "method": self.method,
                "target": self.target, "restore": self.restore}

    @classmethod
    def from_dict(cls, raw: dict) -> "Route | None":
        if not isinstance(raw, dict) or raw.get("method") not in METHODS:
            return None
        country = str(raw.get("country") or "").strip()
        target = str(raw.get("target") or "").strip()
        route = cls(country, raw["method"], target, str(raw.get("restore") or "").strip())
        return route if country and route.targets else None

    def describe(self) -> str:
        return f"{METHOD_LABELS[self.method]}: {self.target}"


def run_command(args: list[str], timeout: float = 20.0) -> tuple[int, str]:
    """Run a command without a console window; returns (exit code, output)."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise RouteError(f"Could not run {os.path.basename(args[0])}: not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RouteError(f"{os.path.basename(args[0])} did not answer in {int(timeout)} seconds.") from exc
    except OSError as exc:
        raise RouteError(f"Could not run {os.path.basename(args[0])}: {exc}") from exc
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


def _find(names: tuple[str, ...], folders: tuple[str, ...]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for folder in folders:
        for name in names:
            path = os.path.join(os.path.expandvars(folder), name)
            if os.path.isfile(path):
                return path
    return None


def find_expressvpn() -> str | None:
    return _find(("expressvpnctl.exe", "expressvpnctl"), (r"%ProgramFiles%\ExpressVPN",
                                                        r"%ProgramFiles(x86)%\ExpressVPN"))


def find_tailscale() -> str | None:
    return _find(("tailscale.exe", "tailscale"), (r"%ProgramFiles%\Tailscale",
                                                  r"%ProgramFiles(x86)%\Tailscale"))


# --- backends ----------------------------------------------------------------
# Each backend offers: available(), snapshot() -> opaque state, apply(route),
# restore(snapshot). They may block for up to CONNECT_TIMEOUT_SECONDS.

class ExpressVpnBackend:
    def __init__(self, run=run_command, sleep=time.sleep, exe: str | None = None):
        self._run, self._sleep, self._exe = run, sleep, exe

    def _ctl(self, *args: str, timeout: float = 20.0) -> str:
        exe = self._exe or find_expressvpn()
        if not exe:
            raise RouteError("ExpressVPN is not installed (expressvpnctl was not found).")
        code, out = self._run([exe, *args], timeout)
        if code != 0:
            raise RouteError(f"ExpressVPN: {out or 'the command failed'}")
        return out.strip()

    def snapshot(self) -> dict:
        return {"state": self._ctl("get", "connectionstate"), "region": self._ctl("get", "region")}

    def _wait_connected(self) -> None:
        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._ctl("get", "connectionstate") == "Connected" and self._dns_ready():
                # Measured with ExpressVPN: the first lookup of a new name can still
                # fail for about three seconds after it reports DNS as ready.
                self._sleep(SETTLE_SECONDS)
                return
            self._sleep(1.0)
        raise RouteError("ExpressVPN did not finish connecting in time.")

    def _dns_ready(self) -> bool:
        """Connected is reported a moment before names resolve through the VPN;
        a station opened in that gap fails with 'could not resolve'."""
        try:
            return self._ctl("get", "dnsconfigured").strip().lower() in ("true", "yes", "1")
        except RouteError:
            return True   # an older ExpressVPN without the flag: connected is all there is

    def apply(self, route: Route) -> None:
        current = self.snapshot()
        if current["state"] == "Connected" and current["region"] == route.target:
            return
        self._ctl("connect", route.target, timeout=CONNECT_TIMEOUT_SECONDS)
        self._wait_connected()

    def restore(self, snapshot: dict) -> None:
        if snapshot.get("state") == "Connected":
            self._ctl("connect", snapshot.get("region") or "smart", timeout=CONNECT_TIMEOUT_SECONDS)
            self._wait_connected()
        else:
            self._ctl("disconnect")
            # Connecting to a route also changes the region ExpressVPN has selected;
            # put the selection back so the next manual connect uses the old one.
            if snapshot.get("region"):
                try:
                    self._ctl("set", "region", snapshot["region"])
                except RouteError as exc:
                    log.warning("Could not restore the selected ExpressVPN region: %s", exc)


class TailscaleBackend:
    def __init__(self, run=run_command, sleep=time.sleep, exe: str | None = None):
        self._run, self._sleep, self._exe = run, sleep, exe

    def _cli(self, *args: str, timeout: float = 20.0) -> str:
        exe = self._exe or find_tailscale()
        if not exe:
            raise RouteError("Tailscale is not installed.")
        code, out = self._run([exe, *args], timeout)
        if code != 0:
            raise RouteError(f"Tailscale: {out or 'the command failed'}")
        return out

    def _status(self) -> dict:
        try:
            return json.loads(self._cli("status", "--json"))
        except ValueError as exc:
            raise RouteError("Tailscale returned an unreadable status.") from exc

    def snapshot(self) -> dict:
        node = (self._status().get("ExitNodeStatus") or {})
        ips = node.get("TailscaleIPs") or []
        return {"exit_node": ips[0].split("/")[0] if ips else ""}

    def apply(self, route: Route) -> None:
        self._cli("set", f"--exit-node={route.target}")
        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if (self._status().get("ExitNodeStatus") or {}).get("Online"):
                return
            self._sleep(1.0)
        raise RouteError(f"The Tailscale exit node '{route.target}' did not come online.")

    def restore(self, snapshot: dict) -> None:
        self._cli("set", f"--exit-node={snapshot.get('exit_node', '')}")


class CommandBackend:
    """Any VPN that can be driven from the command line."""

    def __init__(self, run=run_command):
        self._run = run

    def snapshot(self) -> dict:
        return {}

    def _execute(self, text: str, what: str) -> None:
        try:
            args = shlex.split(text, posix=False)
        except ValueError as exc:
            raise RouteError(f"The {what} command is not valid: {exc}") from exc
        args = [part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part for part in args]
        if not args:
            raise RouteError(f"No {what} command is set.")
        code, out = self._run(args, CONNECT_TIMEOUT_SECONDS)
        if code != 0:
            raise RouteError(f"The {what} command failed: {out or f'exit code {code}'}")

    def apply(self, route: Route) -> None:
        self._execute(route.target, "connect")

    def restore_with(self, route: Route) -> None:
        if route.restore:
            self._execute(route.restore, "disconnect")

    def restore(self, snapshot: dict) -> None:  # restored through restore_with()
        return


# --- manager -----------------------------------------------------------------

@dataclass
class _Applied:
    route: Route
    backend: object
    snapshot: dict = field(default_factory=dict)
    index: int = 0            # which of the route's servers is connected


class RoutingManager:
    """Applies and releases routes. All methods are safe to call from any
    thread and may block, so call them from a worker thread."""

    def __init__(self, config=None, backends: dict | None = None,
                 schedule: Callable[[float, Callable[[], None]], object] | None = None):
        self._config = config
        self._backends = backends or {"expressvpn": ExpressVpnBackend(),
                                      "tailscale": TailscaleBackend(),
                                      "command": CommandBackend()}
        self._schedule = schedule or self._start_timer
        self._lock = threading.RLock()
        self._applied: _Applied | None = None
        self._timer = None

    # settings
    def _get(self, key: str, default):
        config = self._config
        if config is None:
            from radiomaster.utils.config import ConfigManager
            config = ConfigManager.get_instance()
        return config.get(key, default=default)

    @property
    def enabled(self) -> bool:
        return bool(self._get("routing.enabled", False))

    @property
    def mode(self) -> str:
        mode = self._get("routing.mode", MODE_WHEN_BLOCKED)
        return mode if mode in (MODE_ALWAYS, MODE_WHEN_BLOCKED) else MODE_WHEN_BLOCKED

    def routes(self) -> list[Route]:
        raw = self._get("routing.routes", [])
        return [r for r in (Route.from_dict(item) for item in raw or []) if r]

    def route_for(self, country: str) -> Route | None:
        wanted = normalize_country(country)
        if not wanted or not self.enabled:
            return None
        return next((r for r in self.routes() if normalize_country(r.country) == wanted), None)

    @property
    def active(self) -> Route | None:
        return self._applied.route if self._applied else None

    # actions
    def prepare(self, country: str) -> Route | None:
        """Point the VPN at *country* if a route is set for it. Returns the
        route in use, or None when the country has none. Raises RouteError."""
        route = self.route_for(country)
        with self._lock:
            self._cancel_timer()
            if route is None:
                return None
            if self._applied and self._applied.route == route:
                return route
            backend = self._backends[route.method]
            snapshot = self._applied.snapshot if self._applied else backend.snapshot()
            if self._applied and (self._applied.route.method != route.method
                                  or route.method == "command"):
                # A different VPN, or another custom connection, is undone first.
                self._release_locked()
                snapshot = backend.snapshot()
            backend.apply(route.single(route.targets[0]))
            self._applied = _Applied(route, backend, snapshot, 0)
            return route

    @property
    def server(self) -> str:
        """The server of the active route that is connected right now."""
        applied = self._applied
        return applied.route.targets[applied.index] if applied else ""

    def can_advance(self) -> bool:
        """True when the active route has another server to try."""
        applied = self._applied
        return bool(applied and applied.index + 1 < len(applied.route.targets))

    def advance(self) -> str | None:
        """Connect the active route's next server; None when none is left.
        Used when a station still will not play through the current one."""
        with self._lock:
            self._cancel_timer()
            applied = self._applied
            if applied is None or not self.can_advance():
                return None
            server = applied.route.targets[applied.index + 1]
            applied.backend.apply(applied.route.single(server))
            applied.index += 1
            return server

    def release(self) -> None:
        """Put the VPN back as it was before the first route was applied."""
        with self._lock:
            self._cancel_timer()
            self._release_locked()

    def _release_locked(self) -> None:
        applied, self._applied = self._applied, None
        if applied is None:
            return
        try:
            if isinstance(applied.backend, CommandBackend):
                applied.backend.restore_with(applied.route)
            else:
                applied.backend.restore(applied.snapshot)
        except RouteError as exc:
            log.warning("Could not restore the VPN: %s", exc)

    def release_later(self, delay: float = RESTORE_DELAY_SECONDS) -> None:
        """Restore after *delay* unless another route is prepared first."""
        with self._lock:
            if self._applied is None:
                return
            self._cancel_timer()
            self._timer = self._schedule(delay, self.release)

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        cancel = getattr(timer, "cancel", None)
        if cancel:
            cancel()

    @staticmethod
    def _start_timer(delay: float, action: Callable[[], None]):
        timer = threading.Timer(delay, action)
        timer.daemon = True
        timer.start()
        return timer


_manager: RoutingManager | None = None


def get_manager() -> RoutingManager:
    global _manager
    if _manager is None:
        _manager = RoutingManager()
    return _manager
