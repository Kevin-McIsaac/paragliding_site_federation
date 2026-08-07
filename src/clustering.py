"""Groups scored pairs into clusters, conservatively.

Clustering has a failure mode pairwise matching does not: transitive fusion.
If A~B and B~C both score well but A and C are actually different launches,
naive union-find silently merges three records into one site. So a record
joins a cluster only if it clears the auto-link threshold against *every*
member, not merely against one of them.

Pairs that would only have linked transitively are not discarded - they are
returned as review items, because a near-miss between two records that both
sit in the same neighbourhood is exactly what a human should look at.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.matcher import AUTO_LINK_THRESHOLD, Band, ScoredPair
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
    review: list[ScoredPair]


def cluster(
    records: list[SiteRecord],
    pairs: list[ScoredPair],
    rejected: set[frozenset[str]] | None = None,
) -> ClusterResult:
    rejected = rejected or set()
    by_key = {r.key: r for r in records}

    scores: dict[frozenset[str], float] = {}
    for pair in pairs:
        if pair.keys not in rejected:
            scores[pair.keys] = pair.confidence

    mergeable = sorted(
        (p for p in pairs if p.band is Band.AUTO_LINKED and p.keys not in rejected),
        key=lambda p: p.confidence,
        reverse=True,
    )

    cluster_of: dict[str, set[str]] = {r.key: {r.key} for r in records}
    review: list[ScoredPair] = []

    for pair in mergeable:
        left, right = cluster_of[pair.a.key], cluster_of[pair.b.key]
        if left is right:
            continue

        if _fully_connected(left, right, scores):
            merged = left | right
            for key in merged:
                cluster_of[key] = merged
        else:
            # Only linked through a third record - a human decides.
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
        if pair.band in (Band.FLAGGED, Band.CANDIDATE) and pair.keys not in rejected:
            if cluster_of[pair.a.key] is not cluster_of[pair.b.key]:
                review.append(pair)

    review.sort(key=lambda p: p.confidence, reverse=True)
    return ClusterResult(clusters=clusters, review=review)


def _fully_connected(
    left: set[str], right: set[str], scores: dict[frozenset[str], float]
) -> bool:
    """Every cross-cluster pair must independently clear the threshold."""
    for a in left:
        for b in right:
            if scores.get(frozenset({a, b}), 0.0) < AUTO_LINK_THRESHOLD:
                return False
    return True
