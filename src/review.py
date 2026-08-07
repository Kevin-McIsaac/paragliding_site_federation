"""The review list: a markdown table a human reads in the pull request.

Pairs between 100m and 250m apart, closest first. These are not assertions -
they are two launches near enough to be suspicious without being close enough
to merge automatically.

Names link to their source page so a reviewer can open both sides and compare
without going hunting for them.

To decline a pair permanently, add it to rejections.json; otherwise it
reappears every run.
"""

from __future__ import annotations

from pathlib import Path

from rapidfuzz import fuzz

from src.matcher import Pair
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
    lines = ["# Sites to review", ""]

    if merged is not None:
        lines += [f"- **{merged}** merged automatically (under 100 m apart)"]
    lines += [
        f"- **{len(pairs)}** to review below (100–250 m apart)",
        "",
        "Two launches from different sources, near enough to be possible",
        "duplicates but not near enough to merge automatically. Closest first.",
        "Names link to their source page. Name match is context only — it does",
        "not affect merging, and a low score is the part worth looking at.",
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
