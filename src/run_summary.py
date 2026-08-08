"""Builds the PR title/body and the run-health anomaly check."""

from __future__ import annotations

from dataclasses import dataclass

from src.matcher import MERGE_DISTANCE_M, Pair
from src.reports import render_review

_ANOMALY_DROP_FRACTION = 0.20


@dataclass(frozen=True)
class SourceStats:
    name: str
    record_count: int
    with_wind: int = 0
    skipped_unchanged: bool = False

    @property
    def wind_coverage(self) -> str:
        if not self.record_count:
            return "—"
        return f"{self.with_wind} ({self.with_wind / self.record_count:.0%})"


@dataclass(frozen=True)
class RunHealth:
    ok: bool
    notes: list[str]


def check_health(stats: list[SourceStats], previous_counts: dict[str, int]) -> RunHealth:
    """A source's record count crashing almost always means an outage or an
    error page parsed as an empty result, not that most sites disappeared."""
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
    review: list[Pair],
    health: RunHealth,
    no_wind: int,
) -> tuple[str, str]:
    title = (
        f"Sync {run_id}: {site_counts['sites']} launches, "
        f"{merged_clusters} merged, {len(review)} to review"
    )

    lines = [
        f"## Site federation sync — {run_id}",
        "",
        "**Sources fetched**",
        "| Source | Status | Records | With wind directions |",
        "|---|---|---:|---:|",
    ]
    for s in stats:
        status = "unchanged, skipped" if s.skipped_unchanged else "fetched"
        lines.append(f"| {s.name} | {status} | {s.record_count} | {s.wind_coverage} |")

    lines += [
        "",
        "**Dataset**",
        f"- {site_counts['sites']} launches across {site_counts['countries']} countries",
        f"- {merged_clusters} backed by more than one source (within {MERGE_DISTANCE_M:.0f} m)",
        f"- {no_wind} with no wind directions from any source",
        f"- {site_counts['written']} country files changed, {site_counts['unchanged']} unchanged",
        "",
        render_review(review, merged_clusters),
        "",
        "To decline a merge permanently, add the pair to `rejections.json`.",
        "",
        "**Run health**",
    ]
    lines += [f"- {note}" for note in health.notes]
    return title, "\n".join(lines)
