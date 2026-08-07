"""Pairwise scoring between source records: gates, weights, bands.

Two changes from v1, both driven by what the first real run showed:

1. Scoring is symmetric. There is no longer a PGE side and an "other" side -
   every source is a peer, so pairs are scored the same way regardless of who
   they came from. Two records from the *same* provider are never compared:
   Site Guide listing several launches at one site is a deliberate
   distinction, not a duplicate to be merged away.

2. Weights are renormalized over the signals actually available for a pair,
   rather than substituting a neutral 0.5 for missing data. Under v1, Site
   Guide AU carrying no wind orientation (and often no altitude) meant 0.35 of
   the weight sat at neutral for nearly every Australian pair, capping even a
   zero-distance, identical-name match near 0.82 and pushing 66 of 79 real
   matches into the flagged band. Renormalizing scores a pair on what is known
   about it instead of penalizing it for what the source never publishes.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from rapidfuzz import fuzz

from src.model import SiteRecord

_CANDIDATE_RADIUS_M = 750.0
_DISTANCE_DECAY_M = 500.0
_ALTITUDE_DECAY_M = 150.0
_COUNTRY_MISMATCH_PENALTY = 0.15

_WEIGHT_DISTANCE = 0.45
_WEIGHT_ORIENTATION = 0.25
_WEIGHT_NAME = 0.20
_WEIGHT_ALTITUDE = 0.10

AUTO_LINK_THRESHOLD = 0.80
FLAGGED_THRESHOLD = 0.55
CANDIDATE_THRESHOLD = 0.30

# Grid cell in degrees of latitude; must exceed the 750m gate (0.00675 deg).
_CELL_DEG = 0.01
_LAT_NEIGHBOURS = 1
# 750m spans more longitude cells the further from the equator you go:
# 0.00675/cos(75 deg) ~= 0.026 deg, i.e. 3 cells. 4 covers every inhabited
# latitude with room to spare and costs nothing.
_LON_NEIGHBOURS = 4


class Band(str, Enum):
    AUTO_LINKED = "auto_linked"
    FLAGGED = "flagged"
    CANDIDATE = "candidate"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class MatchComponents:
    distance_m: float
    distance_score: float
    orientation_score: float | None
    name_score: float | None
    altitude_score: float | None


@dataclass(frozen=True)
class ScoredPair:
    a: SiteRecord
    b: SiteRecord
    confidence: float
    band: Band
    components: MatchComponents
    provenance: str = "computed"

    @property
    def keys(self) -> frozenset[str]:
        return frozenset({self.a.key, self.b.key})


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _explicit_reference(a: SiteRecord, b: SiteRecord) -> bool:
    """Whether either record already names the other.

    PGE publishes an `ffvl_site_id` column, so for some sources this is a real
    structured cross-reference rather than a text heuristic. A reference that
    already exists outranks anything geometry can infer.
    """
    for owner, other in ((a, b), (b, a)):
        declared = owner.raw.get(f"{other.provider}_site_id")
        if declared and str(declared).strip() not in ("", "0") and str(declared) == other.id:
            return True
    return False


def _band_for(score: float) -> Band:
    if score >= AUTO_LINK_THRESHOLD:
        return Band.AUTO_LINKED
    if score >= FLAGGED_THRESHOLD:
        return Band.FLAGGED
    if score >= CANDIDATE_THRESHOLD:
        return Band.CANDIDATE
    return Band.DISCARDED


def score_pair(a: SiteRecord, b: SiteRecord) -> ScoredPair | None:
    """Score one pair, or None if a hard gate disqualifies it."""
    if a.provider == b.provider:
        return None

    distance_m = haversine_m(a.lat, a.lon, b.lat, b.lon)
    if distance_m > _CANDIDATE_RADIUS_M:
        return None

    if _explicit_reference(a, b):
        components = MatchComponents(round(distance_m, 1), 1.0, None, None, None)
        return ScoredPair(a, b, 1.0, Band.AUTO_LINKED, components, "explicit_reference")

    if a.role != b.role:
        return None

    distance_score = max(0.0, 1 - distance_m / _DISTANCE_DECAY_M)
    weighted = [(_WEIGHT_DISTANCE, distance_score)]

    orientation_score = None
    if a.orientation and b.orientation:
        union = a.orientation | b.orientation
        orientation_score = len(a.orientation & b.orientation) / len(union)
        weighted.append((_WEIGHT_ORIENTATION, orientation_score))

    name_score = None
    if a.name and b.name:
        name_score = fuzz.token_sort_ratio(a.name, b.name) / 100
        weighted.append((_WEIGHT_NAME, name_score))

    altitude_score = None
    if a.altitude is not None and b.altitude is not None:
        altitude_score = max(0.0, 1 - abs(a.altitude - b.altitude) / _ALTITUDE_DECAY_M)
        weighted.append((_WEIGHT_ALTITUDE, altitude_score))

    total_weight = sum(w for w, _ in weighted)
    score = sum(w * s for w, s in weighted) / total_weight

    if a.country and b.country and a.country != b.country:
        score -= _COUNTRY_MISMATCH_PENALTY
    score = min(1.0, max(0.0, score))

    components = MatchComponents(
        distance_m=round(distance_m, 1),
        distance_score=round(distance_score, 3),
        orientation_score=round(orientation_score, 3) if orientation_score is not None else None,
        name_score=round(name_score, 3) if name_score is not None else None,
        altitude_score=round(altitude_score, 3) if altitude_score is not None else None,
    )
    return ScoredPair(a, b, round(score, 3), _band_for(score), components)


def _cell(record: SiteRecord) -> tuple[int, int]:
    return int(math.floor(record.lat / _CELL_DEG)), int(math.floor(record.lon / _CELL_DEG))


def scored_pairs(records: list[SiteRecord]) -> Iterator[ScoredPair]:
    """Every pair that survives the gates, found via a coarse spatial index.

    Comparing 11k+ records naively is ~65M pairs; bucketing by ~1km cell and
    only visiting neighbouring cells keeps it near-linear.
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
                pair = score_pair(record, other)
                if pair is not None and pair.band is not Band.DISCARDED:
                    yield pair
