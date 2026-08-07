"""Cross-source matching: hard gates, weighted scoring, greedy 1:1 assignment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

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

_AUTO_LINK_THRESHOLD = 0.80
_FLAGGED_THRESHOLD = 0.55
_CANDIDATE_THRESHOLD = 0.30


class Band(str, Enum):
    AUTO_LINKED = "auto_linked"
    FLAGGED = "auto_linked_flagged"
    CANDIDATE = "candidate"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class MatchComponents:
    distance_m: float
    distance_score: float
    orientation_score: float
    name_score: float
    altitude_score: float


@dataclass(frozen=True)
class Match:
    pge_site: SiteRecord
    source_site: SiteRecord
    confidence: float
    band: Band
    components: MatchComponents
    provenance: str = "computed"


@dataclass(frozen=True)
class MatchResult:
    linked: list[Match]
    candidates: list[Match]
    unmatched: list[SiteRecord]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _has_explicit_reference(pge: SiteRecord, other: SiteRecord) -> bool:
    """Best-effort text scan for a cross-reference already present in either record.

    Not a guaranteed detector - absence of a hit just means normal scoring
    applies, not that no real link exists. A real reference (a URL or ID one
    source already lists pointing at the other) should outrank any computed
    score, which is why this is checked before the role gate and full scoring.
    """
    pge_text = str(pge.raw.get("description", "")).lower()
    if other.id.lower() in pge_text or (other.name and other.name.lower() in pge_text):
        return True

    other_text = " ".join(str(v) for v in other.raw.values() if isinstance(v, str)).lower()
    return "paraglidingearth" in other_text or str(pge.id).lower() in other_text


def _score_pair(pge: SiteRecord, other: SiteRecord) -> tuple[float, MatchComponents, str] | None:
    distance_m = haversine_m(pge.lat, pge.lon, other.lat, other.lon)
    if distance_m > _CANDIDATE_RADIUS_M:
        return None

    if _has_explicit_reference(pge, other):
        components = MatchComponents(
            distance_m=round(distance_m, 1),
            distance_score=1.0,
            orientation_score=1.0,
            name_score=1.0,
            altitude_score=1.0,
        )
        return 1.0, components, "explicit_reference"

    if pge.role != other.role:
        return None

    distance_score = max(0.0, 1 - distance_m / _DISTANCE_DECAY_M)

    if pge.orientation and other.orientation:
        union = pge.orientation | other.orientation
        orientation_score = len(pge.orientation & other.orientation) / len(union) if union else 0.5
    else:
        orientation_score = 0.5

    name_score = fuzz.token_sort_ratio(pge.name, other.name) / 100 if pge.name and other.name else 0.5

    if pge.altitude is not None and other.altitude is not None:
        altitude_score = max(0.0, 1 - abs(pge.altitude - other.altitude) / _ALTITUDE_DECAY_M)
    else:
        altitude_score = 0.5

    score = (
        _WEIGHT_DISTANCE * distance_score
        + _WEIGHT_ORIENTATION * orientation_score
        + _WEIGHT_NAME * name_score
        + _WEIGHT_ALTITUDE * altitude_score
    )
    if pge.country and other.country and pge.country != other.country:
        score -= _COUNTRY_MISMATCH_PENALTY
    score = min(1.0, max(0.0, score))

    components = MatchComponents(
        distance_m=round(distance_m, 1),
        distance_score=round(distance_score, 3),
        orientation_score=round(orientation_score, 3),
        name_score=round(name_score, 3),
        altitude_score=round(altitude_score, 3),
    )
    return score, components, "computed"


def _band_for(score: float) -> Band:
    if score >= _AUTO_LINK_THRESHOLD:
        return Band.AUTO_LINKED
    if score >= _FLAGGED_THRESHOLD:
        return Band.FLAGGED
    if score >= _CANDIDATE_THRESHOLD:
        return Band.CANDIDATE
    return Band.DISCARDED


def match(pge_sites: list[SiteRecord], other_sites: list[SiteRecord]) -> MatchResult:
    """Score every candidate pair, then resolve the linkable bands 1:1 greedily.

    Candidate-band pairs (0.30-0.55) are not subject to mutual exclusion -
    they aren't assertions of truth, so a site may appear in more than one.
    `unmatched` is source sites with zero gate-surviving candidates at all
    (nothing within range/role), distinct from ones that scored too low to
    keep (those are just dropped, not backlogged - a nearby low-scoring
    candidate means PGE likely already has *something* there).
    """
    scored: list[Match] = []
    matched_other_ids: set[str] = set()

    for pge in pge_sites:
        for other in other_sites:
            result = _score_pair(pge, other)
            if result is None:
                continue
            matched_other_ids.add(other.id)
            score, components, provenance = result
            scored.append(Match(pge, other, score, _band_for(score), components, provenance))

    linkable = sorted(
        (m for m in scored if m.band in (Band.AUTO_LINKED, Band.FLAGGED)),
        key=lambda m: m.confidence,
        reverse=True,
    )
    claimed_pge: set[str] = set()
    claimed_other: set[str] = set()
    linked: list[Match] = []
    for m in linkable:
        if m.pge_site.id in claimed_pge or m.source_site.id in claimed_other:
            continue
        claimed_pge.add(m.pge_site.id)
        claimed_other.add(m.source_site.id)
        linked.append(m)

    candidates = [m for m in scored if m.band is Band.CANDIDATE]
    unmatched = [site for site in other_sites if site.id not in matched_other_ids]
    return MatchResult(linked=linked, candidates=candidates, unmatched=unmatched)
