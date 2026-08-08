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

# Column order is dictated by the app, which parses this file *positionally*
# (pge_sites_download_service._parseCsvLine) - so it deliberately matches the
# PGE-only asset it replaces, field for field, with `source` taking the slot
# `last_edit` used to occupy.
#
# Longitude before latitude looks wrong and is kept anyway. Reordering them
# parses perfectly cleanly and silently puts every site in the wrong
# hemisphere, which no row count or import log would catch. Changing this
# means changing the app parser in the same commit, and spot-checking real
# coordinates afterwards.
#
# No url column: every source page is derivable from `source`
# (pge:4632 -> paraglidingearth.com/?site=4632,
#  siteguide_au:106-28 -> siteguide.org.au/sites/details/106).
CSV_COLUMNS = [
    "id",
    "name",
    "longitude",
    "latitude",
    "altitude",
    "country",
    *(f"wind_{d.lower()}" for d in DIRECTIONS),
    "source",
]


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
    """The app's bundle, in the exact column order its parser expects.

    Altitude and country are here because the app reads them in nine places -
    site cards, the edit screen, marker overlays, the flyability table - not
    because the map itself needs them. Rating, hazards and access notes stay
    out: those are looked up from the source when a user opens a site.
    """
    target = path or APP_CSV
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = [",".join(CSV_COLUMNS)]
    for site in sorted(sites, key=lambda s: s.id):
        row = [
            str(site.numeric_id),
            site.name,
            f"{site.lon:.6f}",
            f"{site.lat:.6f}",
            "" if site.altitude is None else f"{site.altitude:.0f}",
            (site.country or "").lower(),
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
