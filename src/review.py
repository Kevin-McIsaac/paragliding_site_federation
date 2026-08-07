"""The review list: a markdown table a human reads in the pull request.

Pairs between 100m and 250m apart, closest first. These are not assertions -
they are two launches near enough to be suspicious without being close enough
to merge automatically.

To decline one permanently, add it to rejections.json; otherwise it reappears
every run.
"""

from __future__ import annotations

from pathlib import Path

from src.matcher import Pair

REVIEW_PATH = Path("REVIEW.md")
_PGE = "pge"
_AU = "siteguide_au"


def render(pairs: list[Pair]) -> str:
    lines = [
        "# Sites to review",
        "",
        "Launches between 100m and 250m apart, from different sources - close",
        "enough to be possible duplicates, not close enough to merge",
        "automatically. Closest first.",
        "",
        "| PGE Name | AU Name | Distance |",
        "|---|---|---:|",
    ]
    for pair in sorted(pairs, key=lambda p: p.distance_m):
        pge = pair.by_provider(_PGE)
        au = pair.by_provider(_AU)
        lines.append(
            f"| {pge.name if pge else '—'} | {au.name if au else '—'} | {pair.distance_m:,.0f} m |"
        )
    if not pairs:
        lines.append("| _none_ | | |")
    return "\n".join(lines) + "\n"


def write_review(pairs: list[Pair], path: Path | None = None) -> bool:
    target = path or REVIEW_PATH
    content = render(pairs)
    if target.exists() and target.read_text() == content:
        return False
    target.write_text(content)
    return True
