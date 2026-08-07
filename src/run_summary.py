"""Builds the PR title/body and the run-health anomaly check."""

from __future__ import annotations

from dataclasses import dataclass

from src.matcher import Band, MatchResult

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
    """Abort-worthy check: a source's record count crashing usually means an
    outage or an empty/error response, not that most sites vanished."""
    notes = []
    ok = True
    for s in stats:
        previous = previous_counts.get(s.name)
        if previous and previous > 0:
            drop = (previous - s.record_count) / previous
            if drop > _ANOMALY_DROP_FRACTION:
                ok = False
                notes.append(f"{s.name}: record count dropped {drop:.0%} ({previous} -> {s.record_count})")
    if ok:
        notes.append("Record counts within normal range for all sources.")
    return RunHealth(ok=ok, notes=notes)


def build_pr(
    *,
    run_id: str,
    stats: list[SourceStats],
    result: MatchResult,
    link_counts: dict[str, int],
    health: RunHealth,
) -> tuple[str, str]:
    flagged = [m for m in result.linked if m.band is Band.FLAGGED]
    auto = [m for m in result.linked if m.band is Band.AUTO_LINKED]

    title = (
        f"Sync {run_id}: +{len(auto)} linked, {len(flagged)} need review, "
        f"{len(result.candidates)} new candidates"
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
        "**Changes**",
        f"- {link_counts.get('added', 0)} new links",
        f"- {len(flagged)} flagged for review",
        f"- {len(result.candidates)} candidates",
        f"- {link_counts.get('unchanged', 0)} existing links unchanged",
        f"- {link_counts.get('skipped_rejected', 0)} previously-rejected matches skipped",
    ]

    if flagged:
        lines += ["", "**Needs your attention**"]
        for i, m in enumerate(flagged, start=1):
            lines.append(
                f'{i}. PGE "{m.pge_site.name}" ↔ {m.source_site.provider} "{m.source_site.name}" '
                f"— {m.confidence:.2f}"
            )

    lines += [
        "",
        f"**Unmatched** — {len(result.unmatched)} source sites with no PGE site within range "
        "(worklist for possible new PGE submissions, not auto-created)",
        "",
        "**Run health**",
    ]
    lines += [f"- {note}" for note in health.notes]

    return title, "\n".join(lines)
