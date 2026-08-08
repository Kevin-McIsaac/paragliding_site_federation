"""Builds the PR body and the run-health anomaly check.

The body is a dashboard, not a copy of the reports. Each section states what
it is, gives its numbers, says plainly whether anything is needed from the
reader, and links to the *rendered* report - a diff shows markdown as source,
and these tables are only readable rendered.

Inlining a whole table duplicated what the diff already showed and grew
without bound; counts do not. Sections are collapsible, and one that needs
attention opens by default so the reader never has to go looking for the
thing that matters. Empty sections still appear, because a missing section
reads as "did that step run?" rather than "nothing found".
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass

from src.clustering import Cluster, ReviewItem, ReviewReason
from src.matcher import MERGE_DISTANCE_M, haversine_m
from src.model import SiteRecord

_ANOMALY_DROP_FRACTION = 0.20



@dataclass(frozen=True)
class SourceStats:
    name: str
    record_count: int
    with_wind: int = 0

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


def file_link(path: str) -> str:
    """Link to a file on the PR branch, rendered rather than as a diff.

    A diff shows markdown as source and CSV as raw text; GitHub renders both
    properly at this URL. Falls back to a bare path outside Actions so local
    runs stay sensible.
    """
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("PR_BRANCH", "sync/federation")
    if not repo:
        return f"`{path}`"
    return f"[{path}]({server}/{repo}/blob/{branch}/{path})"


def report_link(filename: str) -> str:
    return file_link(f"reports/{filename}")


def _action(view: str | None = None, todo: str | None = None) -> str:
    """The closing line of every section: what to do, and where to look.

    Every section ends with one - including those reporting nothing - so the
    way to open a report is always in the same place, rather than appearing
    only when that report happens to be non-empty.
    """
    parts = ["**Nothing needed.**" if todo is None else f"**Optional:** {todo}."]
    if view:
        parts.append(f"View {view}.")
    return " ".join(parts)


def _section(title: str, summary: str, body: list[str], *, attention: bool = False) -> list[str]:
    """A collapsible section. Anything needing attention starts open."""
    marker = "⚠️ " if attention else ""
    return [
        f"<details{' open' if attention else ''}>",
        f"<summary>{marker}<b>{title}</b> — {summary}</summary>",
        "",
        *body,
        "",
        "</details>",
        "",
    ]


def _overrides_warnings(
    entries: list[dict], records: list[SiteRecord], forced_applied: set[frozenset[str]]
) -> list[str]:
    """Overrides silently doing nothing - the failure you would never notice
    unaided, since a stale key looks exactly like a decision being honoured."""
    keys = {r.key for r in records}
    warnings = []
    for entry in entries:
        a, b = entry.get("a", ""), entry.get("b", "")
        if a not in keys or b not in keys:
            warnings.append(f"`{a}` / `{b}` — key not found, so this override does nothing")
        elif entry.get("verdict") == "always" and frozenset({a, b}) not in forced_applied:
            warnings.append(f"`{a}` / `{b}` — forced merge did not apply")
    return warnings


def _spread(cluster: Cluster) -> float:
    members = cluster.members
    return max(
        (
            haversine_m(a.lat, a.lon, b.lat, b.lon)
            for i, a in enumerate(members)
            for b in members[i + 1 :]
        ),
        default=0.0,
    )


def build_pr(
    *,
    run_id: str,
    stats: list[SourceStats],
    site_counts: dict[str, int],
    clusters: list[Cluster],
    review: list[ReviewItem],
    duplicates: list[tuple[SiteRecord, SiteRecord, float]],
    override_entries: list[dict],
    records: list[SiteRecord],
    forced_applied: set[frozenset[str]],
    health: RunHealth,
    no_wind: int,
) -> tuple[str, str]:
    merged = [c for c in clusters if len(c.members) > 1]
    warnings = _overrides_warnings(override_entries, records, forced_applied)
    attention = len(warnings) + (0 if health.ok else 1)

    title = (
        f"Sync {run_id}: {site_counts['sites']} launches, "
        f"{len(merged)} merged, {len(review)} near-misses"
    )

    lines = [f"## Site federation sync — {run_id}", ""]
    if attention:
        lines += [f"> ⚠️ **{attention} item(s) need attention.** Expanded below.", ""]
    else:
        lines += ["> ✅ **No action required.** Everything below is informational.", ""]

    source_rows = ["| Source | Status | Records | With wind |", "|---|---|---:|---:|"]
    for s in stats:
        source_rows.append(f"| {s.name} | fetched | {s.record_count} | {s.wind_coverage} |")
    lines += _section(
        "Sources",
        f"{len(stats)} fetched",
        source_rows + ["", *(f"- {note}" for note in health.notes)],
        attention=not health.ok,
    )

    lines += _section(
        "Merged Sites Dataset",
        f"{site_counts['sites']} launches, {site_counts['countries']} countries",
        [
            f"The merged output the app ships: every launch from every source, "
            f"deduplicated. {site_counts['written']} country files changed, "
            f"{site_counts['unchanged']} unchanged. "
            f"{no_wind} launches have no wind directions from any source.",
            "",
            _action(view=file_link("app/sites.csv")),
        ],
    )

    widest = f", widest gap {max(_spread(c) for c in merged):,.0f} m" if merged else ""
    lines += _section(
        "Merged launches",
        f"{len(merged)} backed by more than one source{widest}",
        [
            f"Folded together because the sources place them within "
            f"{MERGE_DISTANCE_M:.0f} m of each other.",
            "",
            _action(
                view=report_link("merged.md"),
                todo="to undo a merge, copy its override cell from the report",
            ),
        ],
    )

    if review:
        by_reason = Counter(item.reason for item in review)
        review_body = ["Close enough to be suspicious, not close enough to merge:", ""]
        review_body += [
            f"- **{by_reason[reason]}** — {reason.value}"
            for reason in ReviewReason
            if by_reason.get(reason)
        ]
        review_body += [
            "",
            "A run of obviously-matching pairs just past the threshold would mean the "
            "threshold is wrong for that region — that is what this is for.",
            "",
            _action(
                view=report_link("review.md"),
                todo="to force a pair together, copy its override cell from the report",
            ),
        ]
    else:
        review_body = [
            "Nothing close enough to question.",
            "",
            _action(view=report_link("review.md")),
        ]
    lines += _section("Unmerged near-misses", f"{len(review)} pairs", review_body)

    if duplicates:
        per_source = Counter(a.provider for a, _, _ in duplicates)
        counts = ", ".join(f"{n} in {source}" for source, n in sorted(per_source.items()))
        dup_body = [
            f"Two entries in the *same* guide sitting close together ({counts}).",
            "",
            "Never merged, and `overrides.json` does not affect them — only that guide's "
            "maintainers can say which are mistakes.",
            "",
            _action(
                view=report_link("duplicates.md"),
                todo="reporting these upstream to the guide is worthwhile but outside "
                "this pipeline",
            ),
        ]
    else:
        dup_body = ["None found.", "", _action(view=report_link("duplicates.md"))]
    lines += _section("Possible duplicates within one source", f"{len(duplicates)} pairs", dup_body)

    never = sum(1 for e in override_entries if e.get("verdict") == "never")
    always = sum(1 for e in override_entries if e.get("verdict") == "always")
    if override_entries:
        ov_body = [f"**{never}** pairs forced apart, **{always}** forced together, by hand."]
    else:
        ov_body = ["None. Every decision was made on distance alone."]
    if warnings:
        ov_body += ["", "**These overrides are not doing anything:**", ""]
        ov_body += [f"- {w}" for w in warnings]
        ov_body += [
            "",
            _action(
                view=report_link("overrides.md"),
                todo="fix or remove these entries in `overrides.json`",
            ),
        ]
    else:
        ov_body += ["", _action(view=report_link("overrides.md"))]
    lines += _section(
        "Overrides",
        f"{never} never, {always} always" + (f", {len(warnings)} not applied" if warnings else ""),
        ov_body,
        attention=bool(warnings),
    )

    return title, "\n".join(lines)
