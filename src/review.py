"""A report, not a worklist.

Pairs the pipeline did *not* merge but which sit close enough to be worth a
glance: near-misses just outside the 250m threshold, and pairs blocked by the
one-to-one assignment or the all-pairs guard.

Nothing here needs action. There is deliberately no approve/reject workflow -
when the merge threshold was 100m this list held 21 pairs that were all
obviously the same launch, so a checkbox column would have meant
hand-confirming the default 21 times. The threshold now covers them, and the
rare genuine exception goes in rejections.json by hand.

What this list is *for* is calibration: a cluster of true matches sitting just
past the threshold means the threshold is wrong for that region's data.

Names link to their source page so both sides can be compared directly.
"""

from __future__ import annotations

from pathlib import Path

from rapidfuzz import fuzz

from src.matcher import MERGE_DISTANCE_M, Pair
from src.model import SiteRecord

REVIEW_PATH = Path("REVIEW.md")
_PGE = "pge"
_AU = "siteguide_au"


def name_similarity(a: SiteRecord | None, b: SiteRecord | None) -> float | None:
    """How consistent the two names are, for the reviewer's benefit only.

    Explicitly *not* part of the matching decision - distance alone decides
    that, and this must not creep back into it.

    token_set_ratio, because Site Guide qualifies launch names with their site
    ("Honeysuckle - Launch 3") so one name is routinely a superset of the
    other; token_sort_ratio scores those pairs around 44 despite an obvious
    match. It saturates at 100 for any subset, which is fine here: the useful
    signal is a *low* score, flagging pairs whose names genuinely disagree.
    """
    if a is None or b is None or not a.name or not b.name:
        return None
    return fuzz.token_set_ratio(a.name, b.name)


def _cell(record: SiteRecord | None) -> str:
    if record is None:
        return "—"
    # A pipe in a name would silently break the table row.
    name = record.name.replace("|", "\\|")
    return f"[{name}]({record.url})" if record.url else name


def render(pairs: list[Pair], merged: int | None = None) -> str:
    lines = ["# Unmerged near-misses", ""]

    if merged is not None:
        lines += [f"- **{merged}** merged automatically (within {MERGE_DISTANCE_M:.0f} m)"]
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
        similarity = name_similarity(pge, au)
        lines.append(
            f"| {_cell(pge)} | {_cell(au)} | {pair.distance_m:,.0f} m "
            f"| {'—' if similarity is None else f'{similarity:.0f}%'} |"
        )
    if not pairs:
        lines.append("| _none_ | | | |")

    return "\n".join(lines) + "\n"


def write_review(pairs: list[Pair], merged: int | None = None, path: Path | None = None) -> bool:
    target = path or REVIEW_PATH
    content = render(pairs, merged)
    if target.exists() and target.read_text() == content:
        return False
    target.write_text(content)
    return True
