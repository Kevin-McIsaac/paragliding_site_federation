"""Turns a cluster into one canonical record: whole-record wins, loser fills gaps.

One source is selected per cluster and its values are used wholesale. Any
field it leaves empty falls back to the next source in precedence order, and
every such fallback is recorded in `field_sources` so the origin of a value is
never ambiguous.

The gap-fill is not optional polish. Site Guide AU publishes no wind
orientation at all while PGE has it for every site, and the app feeds
windDirections straight into its flyability calculation and 7-day forecast
table. Strict whole-record selection would blank out flyability on exactly the
Australian sites this project set out to improve.
"""

from __future__ import annotations

from src.clustering import Cluster
from src.ids import IdRegistry
from src.model import MERGED_FIELDS, CanonicalSite, SiteRecord

# Providers that outrank PGE inside their own national scope.
NATIONAL_SCOPE: dict[str, set[str]] = {"siteguide_au": {"AU"}}
_FALLBACK_ORDER = ("pge",)


def _is_empty(value) -> bool:
    return value is None or value == "" or value == frozenset() or value == []


def _rank(record: SiteRecord, country: str | None) -> tuple[int, str]:
    scope = NATIONAL_SCOPE.get(record.provider)
    if scope and country and country in scope:
        return (0, record.provider)  # national guide, in its own country
    if record.provider in _FALLBACK_ORDER:
        return (1, record.provider)
    return (2, record.provider)


def _serialize(value):
    if isinstance(value, frozenset):
        return sorted(value)
    return value


def select(cluster: Cluster, registry: IdRegistry) -> CanonicalSite:
    country = next((m.country for m in cluster.members if m.country), None)
    ordered = sorted(cluster.members, key=lambda m: _rank(m, country))
    winner = ordered[0]

    values: dict = {}
    field_sources: dict[str, str] = {}

    for field_name in MERGED_FIELDS:
        value = getattr(winner, field_name)
        if _is_empty(value):
            for candidate in ordered[1:]:
                fallback = getattr(candidate, field_name)
                if not _is_empty(fallback):
                    value = fallback
                    field_sources[field_name] = candidate.provider
                    break
        values[field_name] = _serialize(value)

    return CanonicalSite(
        id=registry.assign(cluster.keys),
        sources={m.provider: m.id for m in ordered},
        primary=winner.provider,
        values=values,
        field_sources=field_sources,
    )
