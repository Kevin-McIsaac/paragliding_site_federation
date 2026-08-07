"""Builds the PR title/body and the run-health anomaly check."""

from __future__ import annotations

from dataclasses import dataclass

from src.matcher import Band, ScoredPair

_ANOMALY_DROP_FRACTION = 0.20


@dataclass(frozen=True)
class SourceStats:
    name: str
    record_count: int
    skipped_unchanged: bool = False


@dataclass(frozen=True)
class RunHealth:
    ok: bool
    notes: list[str]


def check_health(stats: list[SourceStats], previous_counts: dict[str, int]) -> RunHealth:
    """A source's record count crashing almost always means an outage or an
    error page parsed as an empty result - not that most sites disappeared.
    Aborting beats opening a PR that proposes deleting a country."""
    notes: list[str] = []
    ok = True
    for s in stats:
        if s.skipped_unchanged:
            continue
        previous = previous_counts.get(s.name)
        if previous and previous > 0:
            drop = (previous - s.record_count) / previous
            if drop > _ANOMALY_DROP_FRACTION:
                ok = False
                notes.append(
                    f"{s.name}: record count dropped {drop:.0%} ({previous} -> {s.record_count})"
                )
    if ok:
        notes.append("Record counts within normal range for all sources.")
    return RunHealth(ok=ok, notes=notes)


def build_pr(
    *,
    run_id: str,
    stats: list[SourceStats],
    site_counts: dict[str, int],
    merged_clusters: int,
    review: list[ScoredPair],
    health: RunHealth,
) -> tuple[str, str]:
    flagged = [p for p in review if p.band is Band.FLAGGED]

    title = (
        f"Sync {run_id}: {site_counts['sites']} sites, "
        f"{merged_clusters} merged, {len(review)} to review"
    )

    lines = [
        f"## Site federation sync — {run_id}",
        "",
        "**Sources fetched**",
        "| Source | Status | Records |",
        "|---|---|---|",
    ]
    for s in stats:
        status = "unchanged, skipped" if s.skipped_unchanged else "fetched"
        lines.append(f"| {s.name} | {status} | {s.record_count} |")

    lines += [
        "",
        "**Canonical dataset**",
        f"- {site_counts['sites']} canonical sites across {site_counts['countries']} countries",
        f"- {merged_clusters} sites backed by more than one source",
        f"- {site_counts['written']} country files changed, {site_counts['unchanged']} unchanged",
    ]

    if review:
        lines += ["", f"**Needs your attention** — {len(review)} pairs ({len(flagged)} flagged)"]
        for i, p in enumerate(review[:20], start=1):
            lines.append(
                f'{i}. "{p.a.name}" ({p.a.provider}) ↔ "{p.b.name}" ({p.b.provider}) '
                f"— {p.confidence:.2f}, {p.components.distance_m:.0f}m"
            )
        if len(review) > 20:
            lines.append(f"...and {len(review) - 20} more in `review.json`.")
        lines += [
            "",
            "To decline a merge permanently, add the pair to `rejections.json`.",
        ]

    lines += ["", "**Run health**"]
    lines += [f"- {note}" for note in health.notes]

    return title, "\n".join(lines)
