"""Cross-source duplicate detection, on distance alone.

Two launches from *different* sources are the same launch if they are within
250m of each other. Nothing else is scored.

The threshold was calibrated, not guessed. At 100m the 100-250m band held 21
undecided pairs, and reading them showed essentially all were the same launch
under different naming conventions - "Hill 60" ~ "Hill 60" at 110m, "Cape
Jervis" ~ "Cape Jervis" at 173m, "Serpentine" ~ "Serpentine" at 245m. A review
step there would have meant hand-confirming the default 21 times.

What would have been the only genuinely wrong merges - "Long Reef NE" against
"Long Reef SE" at ~200m - cannot happen anyway: NE matched NE at 14m and SE
matched SE, so both are already claimed by the one-to-one assignment.

Note this is calibrated on Australia alone: English names, good coordinates,
one national source. Sites are far denser in the Alps, so revisit before
adding DHV, FFVL or Flyland rather than assuming 250m generalises.

This replaced a weighted model that also considered name similarity, wind
overlap and altitude. Distance is the one signal every source publishes and
publishes comparably: names differ by convention ("Blackheath" vs "Main
launch"), altitude mixes ASL with AGL, and wind is absent or prose-encoded
depending on the source. Folding those into a single confidence number made
the threshold hard to reason about and impossible to explain in a review.

Records from the same source are never compared - one guide listing several
launches at a site is a deliberate distinction, not a duplicate.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from src.model import SiteRecord

MERGE_DISTANCE_M = 250.0
# Pairs out to here are reported but never merged, so a threshold that has
# drifted wrong for a new source shows up as near-misses rather than silently
# splitting launches.
REVIEW_DISTANCE_M = 400.0

# Grid cell in degrees of latitude; must exceed the 400m report radius
# (400m is 0.0036 deg, comfortably inside one cell).
_CELL_DEG = 0.01
_LAT_NEIGHBOURS = 1
# 400m spans more longitude cells the further from the equator: at 75 degrees
# 0.0036/cos(75) is about 0.014 deg, i.e. two cells. Three is ample everywhere.
_LON_NEIGHBOURS = 3


class Band(str, Enum):
    MERGE = "merge"
    REVIEW = "review"


@dataclass(frozen=True)
class Pair:
    a: SiteRecord
    b: SiteRecord
    distance_m: float
    band: Band

    @property
    def keys(self) -> frozenset[str]:
        return frozenset({self.a.key, self.b.key})

    def by_provider(self, provider: str) -> SiteRecord | None:
        if self.a.provider == provider:
            return self.a
        if self.b.provider == provider:
            return self.b
        return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def pair_for(a: SiteRecord, b: SiteRecord) -> Pair | None:
    if a.provider == b.provider or a.role != b.role:
        return None

    distance_m = haversine_m(a.lat, a.lon, b.lat, b.lon)
    if distance_m > REVIEW_DISTANCE_M:
        return None

    # Known-approximate coordinates cannot evidence a merge, however close.
    if distance_m <= MERGE_DISTANCE_M and not (a.approximate_location or b.approximate_location):
        band = Band.MERGE
    else:
        band = Band.REVIEW
    return Pair(a, b, round(distance_m, 1), band)


def _cell(record: SiteRecord) -> tuple[int, int]:
    return int(math.floor(record.lat / _CELL_DEG)), int(math.floor(record.lon / _CELL_DEG))


def _neighbours(records: list[SiteRecord]) -> Iterator[tuple[SiteRecord, SiteRecord]]:
    """Every nearby pair exactly once, via a spatial index.

    Comparing 11k+ records naively is ~65M combinations; bucketing into ~1km
    cells and visiting only neighbouring cells keeps it near-linear.
    """
    grid: dict[tuple[int, int], list[SiteRecord]] = defaultdict(list)
    for record in records:
        grid[_cell(record)].append(record)

    seen: set[frozenset[str]] = set()
    for (lat_cell, lon_cell), bucket in grid.items():
        neighbourhood: list[SiteRecord] = []
        for dlat in range(-_LAT_NEIGHBOURS, _LAT_NEIGHBOURS + 1):
            for dlon in range(-_LON_NEIGHBOURS, _LON_NEIGHBOURS + 1):
                neighbourhood.extend(grid.get((lat_cell + dlat, lon_cell + dlon), ()))

        for record in bucket:
            for other in neighbourhood:
                if record.key == other.key:
                    continue
                pair_key = frozenset({record.key, other.key})
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                yield record, other


def pairs(records: list[SiteRecord]) -> Iterator[Pair]:
    """Every cross-source pair close enough to be a candidate."""
    for a, b in _neighbours(records):
        if (pair := pair_for(a, b)) is not None:
            yield pair


def intra_source_pairs(records: list[SiteRecord]) -> Iterator[tuple[SiteRecord, SiteRecord, float]]:
    """Suspiciously close pairs from the *same* source - reported, never merged.

    These are invisible to matching by design, because one guide listing
    several launches at a site is a deliberate distinction. But some are real
    duplicates: PGE carries both "Little Europe" and "Lake St Clair" 133m
    apart, and Site Guide's single launch there is named "Glennies Ridge -
    Lake St Clair (Little Europe)" - one place, entered twice.

    Telling those apart from deliberate neighbours needs judgement (Site
    Guide's "Tasman Flying Site 3" and "4" sit 35m apart and are genuinely
    different launches facing opposite ways), so this only reports.
    """
    for a, b in _neighbours(records):
        if a.provider != b.provider or a.role != b.role:
            continue
        # Two launches under one parent site are deliberately distinct.
        if a.group_id is not None and a.group_id == b.group_id:
            continue
        distance_m = haversine_m(a.lat, a.lon, b.lat, b.lon)
        if distance_m <= MERGE_DISTANCE_M:
            first, second = sorted((a, b), key=lambda r: r.id)
            yield first, second, round(distance_m, 1)
