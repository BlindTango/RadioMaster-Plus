"""Which VPN servers belong to which country, and how a chosen list is ordered.

ExpressVPN names its regions like ``uk-london`` or ``usa-washington-dc``. The
station catalog names countries like "United Kingdom Of Great Britain And
Northern Ireland", so the two are matched here, with a few aliases for names
that differ.
"""

from __future__ import annotations

import re
import unicodedata

# ExpressVPN region prefix -> the catalog's slug for that country, where the two differ.
_ALIASES = {
    "uk": "united-kingdom-of-great-britain-and-northern-ireland",
    "usa": "united-states-of-america",
    "czech-republic": "czechia",
    "turkey": "turkiye",
    "moldova": "republic-of-moldova",
    "north-macedonia": "republic-of-north-macedonia",
    "venezuela": "bolivarian-republic-of-venezuela",
    "macau": "macao",
    "brunei": "brunei-darussalam",
    "laos": "lao-peoples-democratic-republic",
    "taiwan": "taiwan-republic-of-china",
    "south-korea": "republic-of-korea",
}
# Entries that are not a place: not listed under any country.
NOT_A_COUNTRY = {"smart", "gaming-europe"}


def slug(text: str) -> str:
    """Lowercase letters and digits joined by hyphens, accents removed, 'the' dropped."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return "-".join(token for token in re.split(r"[^a-z0-9]+", plain.lower())
                    if token and token != "the")


def _prefixes(region: str) -> list[str]:
    """The region's possible country slugs, longest first: ``hong-kong-2`` gives
    ``hong-kong`` then ``hong``; ``india-(via-uk)`` gives ``india-via-uk``..``india``."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", region.lower()) if t and not t.isdigit()]
    return ["-".join(tokens[:n]) for n in range(min(len(tokens), 3), 0, -1)]


def region_matches_country(region: str, country: str) -> bool:
    if region in NOT_A_COUNTRY:
        return False
    target = slug(country)
    if not target:
        return False
    for prefix in _prefixes(region):
        full = _ALIASES.get(prefix, prefix)
        if target == full:
            return True
        # A shortened name still finds an aliased country ("United Kingdom", "UK", "USA").
        # (two words at least: "United" alone could mean the UK, the US or the UAE.)
        if prefix in _ALIASES and (target == prefix or ("-" in target and full.startswith(target + "-"))):
            return True
    return False


def regions_for_country(regions: list[str], country: str) -> list[str]:
    """The ExpressVPN regions in *country*, in ExpressVPN's own order."""
    return [region for region in regions if region_matches_country(region, country)]


def arrange(candidates: list[str], chosen: list[str]) -> list[str]:
    """The list to show: the chosen servers first, in their chosen order (even ones
    that are not among the candidates, so nothing already saved is silently lost),
    then the remaining candidates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for name in [*chosen, *candidates]:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(name)
    return ordered


def move(items: list, index: int, delta: int) -> int:
    """Move items[index] by *delta* places in the list, in place; returns its new
    index (unchanged when it would leave the list)."""
    target = index + delta
    if not (0 <= index < len(items) and 0 <= target < len(items)):
        return index
    items[index], items[target] = items[target], items[index]
    return target
