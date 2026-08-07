"""Writes the canonical dataset, sharded one file per country.

11.4k sites is too many for one file per site (unusable in GitHub's diff
view) and too many for a single global file (every change becomes a
whole-file rewrite). One file per country keeps a single site's change to a
readable few-line diff, with the largest shard around 1,100 sites.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from src.model import CanonicalSite

SITES_DIR = Path("sites")
_UNKNOWN = "xx"


def write_sites(sites: list[CanonicalSite], sites_dir: Path | None = None) -> dict[str, int]:
    directory = sites_dir or SITES_DIR
    directory.mkdir(parents=True, exist_ok=True)

    by_country: dict[str, list[CanonicalSite]] = defaultdict(list)
    for site in sites:
        country = (site.values.get("country") or _UNKNOWN).lower()
        by_country[country].append(site)

    counts = {"countries": 0, "written": 0, "unchanged": 0, "sites": len(sites)}

    for country, group in sorted(by_country.items()):
        path = directory / f"{country}.json"
        payload = [s.to_dict() for s in sorted(group, key=lambda s: s.id)]
        content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        counts["countries"] += 1
        if path.exists() and path.read_text() == content:
            counts["unchanged"] += 1
        else:
            path.write_text(content)
            counts["written"] += 1

    stale = {p.name for p in directory.glob("*.json")} - {f"{c}.json" for c in by_country}
    for name in sorted(stale):
        (directory / name).unlink()

    return counts
