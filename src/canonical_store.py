"""Writes the two artifacts: per-country JSON for review, one CSV for the app.

They have different consumers. The JSON is what a human reviews in a pull
request, so it is sharded per country to keep a single site's change to a
readable few-line diff. The CSV is what the app bundles and loads - one file,
one row per launch, matching the columns the sites table already stores.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from src.model import DIRECTIONS, CanonicalSite

SITES_DIR = Path("sites")
APP_CSV = Path("app/sites.csv")
_UNKNOWN = "xx"

# No url column: every source's page is derivable from its id
# (pge:4632 -> paraglidingearth.com/?site=4632, verified on all 239 AU records;
# siteguide_au:106-28 -> siteguide.org.au/sites/106), and at ~45 bytes a row it
# was the single largest column in a file that ships with every install.
CSV_COLUMNS = ["id", "name", "latitude", "longitude", *(f"wind_{d.lower()}" for d in DIRECTIONS), "source"]


def write_sites(sites: list[CanonicalSite], sites_dir: Path | None = None) -> dict[str, int]:
    directory = sites_dir or SITES_DIR
    directory.mkdir(parents=True, exist_ok=True)

    by_country: dict[str, list[CanonicalSite]] = defaultdict(list)
    for site in sites:
        by_country[(site.country or _UNKNOWN).lower()].append(site)

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


def write_app_csv(sites: list[CanonicalSite], path: Path | None = None) -> bool:
    """The app's bundle: name, position, wind and a source link. Nothing else.

    Altitude, rating, hazards and access notes are deliberately absent - they
    are looked up from the source when a user opens a site, so they do not
    need to ship with every install.
    """
    target = path or APP_CSV
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = [",".join(CSV_COLUMNS)]
    for site in sorted(sites, key=lambda s: s.id):
        row = [
            site.id,
            site.name,
            f"{site.lat:.6f}",
            f"{site.lon:.6f}",
            *(str(site.wind.get(d, 0)) for d in DIRECTIONS),
            ";".join(f"{p}:{i}" for p, i in sorted(site.sources.items())),
        ]
        lines.append(_csv_row(row))
    content = "\n".join(lines) + "\n"

    if target.exists() and target.read_text() == content:
        return False
    target.write_text(content)
    return True


def _csv_row(values: list[str]) -> str:
    import io

    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(values)
    return buffer.getvalue()
