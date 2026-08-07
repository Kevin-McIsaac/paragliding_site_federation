"""Cross-source duplicate detection, on distance alone.

Two launches from *different* sources are the same launch if they are within
100m of each other; between 100m and 250m a human decides; beyond that they
are separate. Nothing else is scored.

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

MERGE_DISTANCE_M = 100.0
REVIEW_DISTANCE_M = 250.0

# Grid cell in degrees of latitude; must exceed the 250m review radius.
_CELL_DEG = 0.01
_LAT_NEIGHBOURS = 1
# 250m spans more longitude cells the further from the equator: at 75 degrees
# 0.00225/cos(75) is about 0.0087 deg, i.e. one cell. Two is ample everywhere.
_LON_NEIGHBOURS = 2


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


def pairs(records: list[SiteRecord]) -> Iterator[Pair]:
    """Every cross-source pair within the review radius, via a spatial index.

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
                if (pair := pair_for(record, other)) is not None:
                    yield pair
