"""The two human-readable markdown reports.

MERGED.md  - what the pipeline folded together, and how far apart the sources
             put it. This is the record of every decision actually taken.
REVIEW.md  - what it did *not* merge but which sits close enough to be worth
             a glance.

Neither is a worklist. There is deliberately no approve/reject workflow: when
the merge threshold was 100m the review list held 21 pairs that were all
obviously the same launch, so a checkbox column would have meant
hand-confirming the default 21 times. The threshold covers them now, and the
rare genuine exception goes in rejections.json by hand.

What the reports are *for* is calibration and audit - a run of true matches
sitting just past the threshold means the threshold is wrong for that region's
data, and MERGED.md is how you check that a merge you doubt was reasonable.
"""

from __future__ import annotations

from pathlib import Path

from rapidfuzz import fuzz

from src.clustering import Cluster
from src.matcher import MERGE_DISTANCE_M, Pair, haversine_m
from src.model import SiteRecord

MERGED_PATH = Path("MERGED.md")
REVIEW_PATH = Path("REVIEW.md")
REJECTED_PATH = Path("REJECTED.md")
_PGE = "pge"
_AU = "siteguide_au"


def link_cell(record: SiteRecord | None) -> str:
    if record is None:
        return "—"
    # A pipe in a name would silently break the table row.
    name = record.name.replace("|", "\\|")
    return f"[{name}]({record.url})" if record.url else name


def name_similarity(a: SiteRecord | None, b: SiteRecord | None) -> float | None:
    """How consistent two names are, for the reader's benefit only.

    Explicitly *not* part of the matching decision - distance alone decides
    that, and this must not creep back into it.

    token_set_ratio, because Site Guide qualifies launch names with their site
    ("Honeysuckle - Launch 3") so one name is routinely a superset of the
    other; token_sort_ratio scores those pairs around 44 despite an obvious
    match. It saturates at 100 for any subset, which is fine here: the useful
    signal is a *low* score, flagging names that genuinely disagree.
    """
    if a is None or b is None or not a.name or not b.name:
        return None
    return fuzz.token_set_ratio(a.name, b.name)


def _similarity_cell(a: SiteRecord | None, b: SiteRecord | None) -> str:
    score = name_similarity(a, b)
    return "—" if score is None else f"{score:.0f}%"


def _member(cluster: Cluster, provider: str) -> SiteRecord | None:
    return next((m for m in cluster.members if m.provider == provider), None)


def _spread_m(cluster: Cluster) -> float:
    """Furthest apart any two members are - the distance that was bridged."""
    members = cluster.members
    return max(
        (haversine_m(a.lat, a.lon, b.lat, b.lon) for i, a in enumerate(members) for b in members[i + 1 :]),
        default=0.0,
    )


def render_merged(clusters: list[Cluster]) -> str:
    merged = [c for c in clusters if len(c.members) > 1]
    rows = sorted(((_spread_m(c), c) for c in merged), key=lambda t: t[0])

    lines = [
        "# Merged launches",
        "",
        f"- **{len(merged)}** launches backed by more than one source",
        "",
        f"Folded together because the sources place them within "
        f"{MERGE_DISTANCE_M:.0f} m of each other. Distance is how far apart they",
        "actually were. Names link to their source page; name match is context",
        "only and played no part in the decision — a low score here is worth a",
        "look. To stop a pair being merged, add it to `rejections.json`.",
        "",
        "| PGE Name | AU Name | Distance | Name match |",
        "|---|---|---:|---:|",
    ]
    for distance, cluster in rows:
        pge, au = _member(cluster, _PGE), _member(cluster, _AU)
        lines.append(
            f"| {link_cell(pge)} | {link_cell(au)} | {distance:,.0f} m "
            f"| {_similarity_cell(pge, au)} |"
        )
    if not merged:
        lines.append("| _none_ | | | |")
    return "\n".join(lines) + "\n"


def render_review(pairs: list[Pair], merged: int | None = None) -> str:
    lines = ["# Unmerged near-misses", ""]
    if merged is not None:
        lines += [f"- **{merged}** merged automatically (within {MERGE_DISTANCE_M:.0f} m) — see `MERGED.md`"]
    lines += [
        f"- **{len(pairs)}** left unmerged but close, listed below",
        "",
        "Nothing here needs action — this is a report, not a worklist. A run of",
        f"true matches just past {MERGE_DISTANCE_M:.0f} m would mean the threshold is wrong for this",
        "region; that is what to watch for. To stop a specific pair being merged,",
        "add it to `rejections.json`.",
        "",
        "Names link to their source page. Name match is context only — it plays",
        "no part in merging, and a low score is the part worth a look.",
        "",
        "| PGE Name | AU Name | Distance | Name match |",
        "|---|---|---:|---:|",
    ]
    for pair in sorted(pairs, key=lambda p: p.distance_m):
        pge, au = pair.by_provider(_PGE), pair.by_provider(_AU)
        lines.append(
            f"| {link_cell(pge)} | {link_cell(au)} | {pair.distance_m:,.0f} m "
            f"| {_similarity_cell(pge, au)} |"
        )
    if not pairs:
        lines.append("| _none_ | | | |")
    return "\n".join(lines) + "\n"


def render_rejected(entries: list[dict], records: list[SiteRecord]) -> str:
    """The readable view of rejections.json, with keys resolved to names.

    A key can go stale - a source may drop or renumber a site - so anything
    that no longer resolves is shown as its raw key and flagged, rather than
    silently disappearing. A stale entry is dead weight suppressing nothing.
    """
    by_key = {r.key: r for r in records}

    lines = [
        "# Declined merges",
        "",
        f"- **{len(entries)}** pairs will never be merged",
        "",
        "The readable view of `rejections.json`, which is the only file you edit",
        "by hand. Add a pair there to stop it being merged; everything else the",
        "pipeline decides on its own.",
        "",
        "| PGE Name | AU Name | Reason | Still present? |",
        "|---|---|---|---|",
    ]
    for entry in sorted(entries, key=lambda e: (e.get("a", ""), e.get("b", ""))):
        keys = [entry.get("a", ""), entry.get("b", "")]
        resolved = [by_key.get(k) for k in keys]
        pge = next((r for r in resolved if r and r.provider == _PGE), None)
        au = next((r for r in resolved if r and r.provider == _AU), None)

        cells = []
        for record, key in ((pge, next((k for k in keys if k.startswith(f"{_PGE}:")), None)),
                            (au, next((k for k in keys if k.startswith(f"{_AU}:")), None))):
            cells.append(link_cell(record) if record else (f"`{key}`" if key else "—"))

        stale = any(r is None for r in resolved)
        status = "⚠️ key not found — stale?" if stale else "yes"
        reason = str(entry.get("reason", "—")).replace("|", "\\|")
        lines.append(f"| {cells[0]} | {cells[1]} | {reason} | {status} |")

    if not entries:
        lines.append("| _none_ | | | |")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def write_merged(clusters: list[Cluster], path: Path | None = None) -> bool:
    return _write_if_changed(path or MERGED_PATH, render_merged(clusters))


def write_review(pairs: list[Pair], merged: int | None = None, path: Path | None = None) -> bool:
    return _write_if_changed(path or REVIEW_PATH, render_review(pairs, merged))


def write_rejected(entries: list[dict], records: list[SiteRecord], path: Path | None = None) -> bool:
    return _write_if_changed(path or REJECTED_PATH, render_rejected(entries, records))
