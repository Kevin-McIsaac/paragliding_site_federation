"""Groups merge-band pairs into clusters, conservatively.

A record joins a cluster only if it is within the merge distance of *every*
member, not merely one. Without that, A-B and B-C both under 100m would chain
A and C together even when they are 190m apart and genuinely distinct.

Pairs that would only have linked transitively become review items, alongside
the ones that landed in the review band on distance alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.matcher import MERGE_DISTANCE_M, Band, Pair
from src.model import SiteRecord


class ReviewReason(str, Enum):
    #: Close enough to merge, but the other side already merged with something
    #: nearer. PGE's "Lake St Clair" sits 100m from a Site Guide launch that
    #: PGE's own "Little Europe" already claimed at 33m - the symptom of a
    #: duplicate *within* PGE, which cross-source matching cannot resolve.
    COUNTERPART_MERGED = "counterpart already merged"
    #: Close enough to merge, but joining would have pulled together records
    #: that are not all within the threshold of each other.
    CLUSTER_GUARD = "would over-merge the cluster"
    #: Simply further apart than the merge threshold.
    BEYOND_THRESHOLD = "beyond merge threshold"


@dataclass(frozen=True)
class ReviewItem:
    pair: Pair
    reason: ReviewReason

    @property
    def distance_m(self) -> float:
        return self.pair.distance_m


@dataclass(frozen=True)
class Cluster:
    members: tuple[SiteRecord, ...]

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(m.key for m in self.members)


@dataclass(frozen=True)
class ClusterResult:
    clusters: list[Cluster]
    review: list[ReviewItem]
    #: Forced pairs whose keys both resolved. Anything in the overrides file
    #: but missing here has a stale key and is silently doing nothing.
    forced_applied: set[frozenset[str]] = field(default_factory=set)


def cluster(
    records: list[SiteRecord],
    pairs: list[Pair],
    rejected: set[frozenset[str]] | None = None,
    forced: set[frozenset[str]] | None = None,
) -> ClusterResult:
    rejected = rejected or set()
    forced = forced or set()
    by_key = {r.key: r for r in records}

    distances = {p.keys: p.distance_m for p in pairs if p.keys not in rejected}
    mergeable = sorted(
        (p for p in pairs if p.band is Band.MERGE and p.keys not in rejected),
        key=lambda p: p.distance_m,
    )

    cluster_of: dict[str, set[str]] = {r.key: {r.key} for r in records}

    # Forced pairs seed clusters before merging starts. They never arrive as
    # scored pairs - a pair 387m apart, or a launch against a landing, would
    # not survive the gates - so joining them here is what makes "always"
    # meaningful. A key that no longer resolves is skipped; the overrides
    # report flags it rather than failing the run.
    applied_forced: set[frozenset[str]] = set()
    for keys in forced:
        a, b = sorted(keys)
        if a not in cluster_of or b not in cluster_of:
            continue
        applied_forced.add(keys)
        merged = cluster_of[a] | cluster_of[b]
        for key in merged:
            cluster_of[key] = merged

    blocked: list[Pair] = []

    for pair in mergeable:
        left, right = cluster_of[pair.a.key], cluster_of[pair.b.key]
        if left is right:
            continue
        if _all_within(left, right, distances, applied_forced):
            merged = left | right
            for key in merged:
                cluster_of[key] = merged
        else:
            blocked.append(pair)

    seen: list[set[str]] = []
    clusters: list[Cluster] = []
    for key in sorted(cluster_of):
        group = cluster_of[key]
        if any(group is s for s in seen):
            continue
        seen.append(group)
        clusters.append(Cluster(members=tuple(by_key[k] for k in sorted(group))))

    # A pair where both records already merged with someone else is settled,
    # not a question - the one-to-one assignment gave each a better partner.
    # "Long Reef NE" ~ "Long Reef SE" is the case: each matched its own
    # counterpart at ~14m, so listing the 200m cross-pair only invites action
    # on something that cannot happen.
    spoken_for = {k for c in clusters if len(c.members) > 1 for k in c.keys}

    review: list[ReviewItem] = []
    for pair in blocked:
        if pair.a.key in spoken_for and pair.b.key in spoken_for:
            continue
        # Being blocked while the other side is already merged is a different
        # story from over-merging: it usually means that side's own source
        # holds a duplicate. Naming them apart saves the reader working out
        # why a 100m pair did not merge.
        reason = (
            ReviewReason.COUNTERPART_MERGED
            if pair.a.key in spoken_for or pair.b.key in spoken_for
            else ReviewReason.CLUSTER_GUARD
        )
        review.append(ReviewItem(pair, reason))

    for pair in pairs:
        if pair.band is Band.REVIEW and pair.keys not in rejected and pair.keys not in forced:
            if cluster_of[pair.a.key] is not cluster_of[pair.b.key]:
                if pair.a.key in spoken_for and pair.b.key in spoken_for:
                    continue
                review.append(ReviewItem(pair, ReviewReason.BEYOND_THRESHOLD))

    review.sort(key=lambda item: item.distance_m)
    return ClusterResult(clusters=clusters, review=review, forced_applied=applied_forced)


def _all_within(
    left: set[str],
    right: set[str],
    distances: dict[frozenset[str], float],
    forced: set[frozenset[str]],
) -> bool:
    """Every cross-cluster pair must be within the threshold - except one a
    human forced, whose whole point is that the distance does not apply."""
    for a in left:
        for b in right:
            keys = frozenset({a, b})
            if keys in forced:
                continue
            if distances.get(keys, float("inf")) > MERGE_DISTANCE_M:
                return False
    return True
