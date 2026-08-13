"""Turns a cluster into one canonical launch.

A national guide outranks PGE inside its own country, so its name and
coordinates win. Wind comes from the winner too, falling back to another
source only when the winner has none at all - which happens for the ~26 Site
Guide sites whose conditions prose does not parse.

Note the accepted consequence of that rule: PGE grades directions 0/1/2 while
parsed Site Guide prose can only ever say "in range" (1), so a Site
Guide-primary launch never shows "excellent" even when PGE rated it so.

Measured, so the trade is a known size rather than a vague one: 61% of
PGE-primary launches (6,974 of 11,419) carry at least one "excellent", against 1
of the 89 Australian launches both guides describe. So most of those 89 are
giving up a grade PGE had. Kept deliberately - the local guide is the authority
on which aspects a hill actually works in, and mixing one guide's directions with
another's severity would publish a rating no guide ever gave.
"""

from __future__ import annotations

import logging

from src.clustering import Cluster
from src.ids import IdRegistry
from src.model import CanonicalSite, SiteRecord

LOGGER = logging.getLogger(__name__)

#: Which guides are authoritative inside which countries, most authoritative
#: first. A list, not a set, because two guides may one day cover one country and
#: the order then has to be a decision rather than a coincidence - it used to
#: fall out of `sorted` on the provider name, so `aaa` would have outranked
#: `ansg` for no reason anyone chose.
NATIONAL_SCOPE: dict[str, list[str]] = {"ansg": ["AU"], "dhv": ["DE", "AT", "CH"]}
_FALLBACK_ORDER = ("pge",)


def _national_rank(provider: str, country: str | None) -> int | None:
    """Where `provider` sits among the guides authoritative in `country`."""
    if country is None:
        return None
    scoped = [p for p, countries in NATIONAL_SCOPE.items() if country in countries]
    return scoped.index(provider) if provider in scoped else None


def _rank(record: SiteRecord, country: str | None) -> tuple[int, int, str]:
    national = _national_rank(record.provider, country)
    if national is not None:
        return (0, national, record.provider)
    if record.provider in _FALLBACK_ORDER:
        return (1, 0, record.provider)
    return (2, 0, record.provider)


def country_of(cluster: Cluster) -> str | None:
    """Which country the cluster is in, for deciding who is authoritative there.

    This used to be the first non-null country among the members, which made the
    ranking below depend on member order: if a national guide said AU and PGE
    said NZ, whichever happened to come first decided whose name and wind won.
    Silent, and it flips on an upstream reordering.

    A guide that only covers one country is the better authority on whether a
    launch is in it, so a scoped provider's answer wins. Disagreements are
    reported rather than absorbed - the clustering matched two records claiming
    different countries, which is worth a human look either way.
    """
    claimed = {m.country for m in cluster.members if m.country}
    if len(claimed) <= 1:
        return next(iter(claimed), None)

    scoped = [
        m.country
        for m in cluster.members
        if m.country and m.provider in NATIONAL_SCOPE
    ]
    chosen = scoped[0] if scoped else sorted(claimed)[0]
    LOGGER.warning(
        "cluster %s claims countries %s; using %s",
        sorted(cluster.keys),
        sorted(claimed),
        chosen,
    )
    return chosen


def select(cluster: Cluster, registry: IdRegistry) -> CanonicalSite:
    country = country_of(cluster)
    ordered = sorted(cluster.members, key=lambda m: _rank(m, country))
    winner = ordered[0]

    # Every member shares a role - `pair_for` refuses to pair across them - so
    # the winner's is the cluster's.
    role = winner.role

    # A landing has no wind, whatever a source attached to it. PGE types a
    # record as a landing from its name while still publishing the takeoff's
    # wind on it, and two such records exist; carried through, the app would
    # colour a landing green and call it flyable.
    wind = {} if role == "landing" else winner.wind
    if not wind and role != "landing":
        wind = next((m.wind for m in ordered[1:] if m.wind), {})

    altitude = winner.altitude
    if altitude is None:
        altitude = next((m.altitude for m in ordered[1:] if m.altitude is not None), None)

    # Same gap-fill as altitude. DHV publishes no landing text at all, so a
    # DHV-primary landing that PGE also describes would otherwise lose the only
    # words anyone wrote about it.
    notes = winner.notes or next((m.notes for m in ordered[1:] if m.notes), None)

    # Closure is the one field not taken from the winner. One guide knowing a
    # site is shut is reason enough to say so - a pilot wants the warning even
    # if the guide that raised it lost on every other field.
    closed = next((m.closed for m in ordered if m.closed), None)

    # Tow follows the same rule and for the same reason: a pilot arriving at a
    # flat field expecting a hill has been misled by whichever guide stayed
    # quiet, so one guide saying so is enough.
    tow = any(m.tow for m in ordered)

    # One token per parent, per guide. A landing carries the same tokens as the
    # launches it serves, which is how the app joins them - and it can carry
    # several, since one field often serves more than one launch.
    group = tuple(
        sorted({f"{m.provider}:{gid}" for m in ordered for gid in m.group_ids})
    )

    return CanonicalSite(
        id=registry.assign(cluster.keys),
        name=winner.name,
        lat=winner.lat,
        lon=winner.lon,
        wind=dict(wind),
        sources={m.provider: m.id for m in ordered},
        primary=winner.provider,
        role=role,
        tow=tow,
        group=group,
        notes=notes,
        altitude=altitude,
        country=country,
        url=winner.url,
        closed=closed,
    )
