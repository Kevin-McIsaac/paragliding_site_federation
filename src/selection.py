"""Turns a cluster into one canonical launch.

A national guide outranks PGE inside its own country, so its name and
coordinates win. Wind comes from the winner too, falling back to another
source only when the winner has none at all - which happens for the ~26 Site
Guide sites whose conditions prose does not parse.

Note the accepted consequence of that rule: PGE grades directions 0/1/2 while
parsed Site Guide prose can only ever say "in range" (1), so a Site
Guide-primary launch never shows "excellent" even when PGE rated it so.
"""

from __future__ import annotations

from src.clustering import Cluster
from src.ids import IdRegistry
from src.model import CanonicalSite, SiteRecord

NATIONAL_SCOPE: dict[str, set[str]] = {"ansg": {"AU"}}
_FALLBACK_ORDER = ("pge",)


def _rank(record: SiteRecord, country: str | None) -> tuple[int, str]:
    scope = NATIONAL_SCOPE.get(record.provider)
    if scope and country and country in scope:
        return (0, record.provider)
    if record.provider in _FALLBACK_ORDER:
        return (1, record.provider)
    return (2, record.provider)


def select(cluster: Cluster, registry: IdRegistry) -> CanonicalSite:
    country = next((m.country for m in cluster.members if m.country), None)
    ordered = sorted(cluster.members, key=lambda m: _rank(m, country))
    winner = ordered[0]

    wind = winner.wind
    if not wind:
        wind = next((m.wind for m in ordered[1:] if m.wind), {})

    altitude = winner.altitude
    if altitude is None:
        altitude = next((m.altitude for m in ordered[1:] if m.altitude is not None), None)

    # Closure is the one field not taken from the winner. One guide knowing a
    # site is shut is reason enough to say so - a pilot wants the warning even
    # if the guide that raised it lost on every other field.
    closed = next((m.closed for m in ordered if m.closed), None)

    return CanonicalSite(
        id=registry.assign(cluster.keys),
        name=winner.name,
        lat=winner.lat,
        lon=winner.lon,
        wind=dict(wind),
        sources={m.provider: m.id for m in ordered},
        primary=winner.provider,
        altitude=altitude,
        country=country,
        url=winner.url,
        closed=closed,
    )
