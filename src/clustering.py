"""Groups merge-band pairs into clusters, conservatively.

A record joins a cluster only if it is within the merge distance of *every*
member, not merely one. Without that, A-B and B-C both under 100m would chain
A and C together even when they are 190m apart and genuinely distinct.

Pairs that would only have linked transitively become review items, alongside
the ones that landed in the review band on distance alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.matcher import MERGE_DISTANCE_M, Band, Pair
from src.model import SiteRecord


@dataclass(frozen=True)
class Cluster:
    members: tuple[SiteRecord, ...]

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(m.key for m in self.members)


@dataclass(frozen=True)
class ClusterResult:
    clusters: list[Cluster]
    review: list[Pair]


def cluster(
    records: list[SiteRecord],
    pairs: list[Pair],
    rejected: set[frozenset[str]] | None = None,
) -> ClusterResult:
    rejected = rejected or set()
    by_key = {r.key: r for r in records}

    distances = {p.keys: p.distance_m for p in pairs if p.keys not in rejected}
    mergeable = sorted(
        (p for p in pairs if p.band is Band.MERGE and p.keys not in rejected),
        key=lambda p: p.distance_m,
    )

    cluster_of: dict[str, set[str]] = {r.key: {r.key} for r in records}
    review: list[Pair] = []

    for pair in mergeable:
        left, right = cluster_of[pair.a.key], cluster_of[pair.b.key]
        if left is right:
            continue
        if _all_within(left, right, distances):
            merged = left | right
            for key in merged:
                cluster_of[key] = merged
        else:
            review.append(pair)

    seen: list[set[str]] = []
    clusters: list[Cluster] = []
    for key in sorted(cluster_of):
        group = cluster_of[key]
        if any(group is s for s in seen):
            continue
        seen.append(group)
        clusters.append(Cluster(members=tuple(by_key[k] for k in sorted(group))))

    for pair in pairs:
        if pair.band is Band.REVIEW and pair.keys not in rejected:
            if cluster_of[pair.a.key] is not cluster_of[pair.b.key]:
                review.append(pair)

    review.sort(key=lambda p: p.distance_m)
    return ClusterResult(clusters=clusters, review=review)


def _all_within(left: set[str], right: set[str], distances: dict[frozenset[str], float]) -> bool:
    for a in left:
        for b in right:
            if distances.get(frozenset({a, b}), float("inf")) > MERGE_DISTANCE_M:
                return False
    return True
