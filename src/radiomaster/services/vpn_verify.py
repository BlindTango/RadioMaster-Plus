"""Confirm which region-blocked stations really do play through a VPN.

The Health Check finds stations that refuse listeners outside their own country.
This connects the VPN to each such country in turn (using the Regional routing
routes), tries every blocked station of that country, and records the ones that
play as confirmed. The VPN is always put back afterwards.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from radiomaster.services.region_block import region_block_status
from radiomaster.services.routing import RouteError, RoutingManager
from radiomaster.services.stream_prober import probe_stream_format


@dataclass
class VerifyResult:
    confirmed: int = 0
    still_failing: int = 0
    custom_unconfirmed: int = 0        # stations the listener added that did not play (kept)
    skipped_countries: list[str] = field(default_factory=list)   # no route set
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def checked(self) -> int:
        return self.confirmed + self.still_failing + self.custom_unconfirmed

    def summary(self) -> str:
        parts = [f"{self.confirmed} of {self.checked} blocked station(s) confirmed to play through a VPN"]
        if self.still_failing:
            parts.append(f"{self.still_failing} did not play even through the VPN, so they "
                         "are dead rather than region-blocked")
        if self.custom_unconfirmed:
            parts.append(f"{self.custom_unconfirmed} station(s) you added did not play and "
                         "were kept; they may be off the air")
        if self.skipped_countries:
            parts.append("no route set for " + ", ".join(self.skipped_countries))
        if self.errors:
            parts.append("; ".join(self.errors))
        if self.cancelled:
            parts.append("stopped early")
        return ". ".join(parts) + "."


def _plays(url: str) -> bool:
    return region_block_status(url) is None and bool(probe_stream_format(url, timeout=12.0))


def verify_vpn_stations(db, manager: RoutingManager, *, cancel: threading.Event | None = None,
                        progress: Callable[[str], None] | None = None,
                        workers: int = 4) -> VerifyResult:
    """Runs on a worker thread; can take a minute per country."""
    cancel = cancel or threading.Event()
    say = progress or (lambda _text: None)
    result = VerifyResult()
    by_country: dict[str, list[dict]] = {}
    for row in db.vpn_required():
        by_country.setdefault(row["country"], []).append(row)
    try:
        for country, stations in by_country.items():
            if cancel.is_set():
                break
            if manager.route_for(country) is None:
                result.skipped_countries.append(country)
                continue
            say(f"Connecting the VPN for {country} ({len(stations)} station(s))...")
            try:
                manager.prepare(country)
            except RouteError as exc:
                result.errors.append(f"{country}: {exc}")
                continue
            remaining = list(stations)
            while remaining and not cancel.is_set():
                say(f"Testing {len(remaining)} station(s) through {manager.server or 'the VPN'} "
                    f"for {country}...")
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    outcomes = list(pool.map(
                        lambda s: (s, False if cancel.is_set() else _plays(s["url"])), remaining))
                failed = []
                for station, ok in outcomes:
                    if ok:
                        db.set_vpn_verified(station["uuid"], True)
                        result.confirmed += 1
                    else:
                        failed.append(station)
                remaining = failed
                if not remaining or cancel.is_set():
                    break
                # A broadcaster can block one VPN server and not another in the same
                # country, so try the route's other servers before giving up.
                try:
                    server = manager.advance()
                except RouteError as exc:
                    result.errors.append(f"{country}: {exc}")
                    break
                if server is None:
                    break
                say(f"{len(remaining)} station(s) did not play; trying {server}...")
            if cancel.is_set():
                break
            for station in remaining:
                if station["uuid"].startswith("custom-"):
                    # A station the listener added keeps its place: it may simply be
                    # off the air right now (a sports stream between matches).
                    result.custom_unconfirmed += 1
                else:
                    # Refused from abroad and silent from inside the country through
                    # every server: it is dead, not region-blocked.
                    db.mark_dead_through_vpn(station["uuid"], country)
                    result.still_failing += 1
    finally:
        say("Putting the VPN back...")
        manager.release()
        result.cancelled = cancel.is_set()
    return result
