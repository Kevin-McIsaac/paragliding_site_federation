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

# The app reads this by column *name*, so order is not load-bearing. It used
# to be: the app split on newlines and read fixed indices, which made
# longitude-before-latitude a permanent trap - swap them and every site lands
# in the wrong hemisphere while still parsing cleanly. The order below is kept
# only because it matches the asset this replaced, which makes a diff between
# two versions of the file far easier to read.
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
    "closed",
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
            _lf(site.name),
            f"{site.lon:.6f}",
            f"{site.lat:.6f}",
            "" if site.altitude is None else f"{site.altitude:.0f}",
            (site.country or "").lower(),
            *(str(site.wind.get(d, 0)) for d in DIRECTIONS),
            ";".join(f"{p}:{i}" for p, i in sorted(site.sources.items())),
            _lf(site.closed or ""),
        ]
        lines.append(_csv_row(row))
    content = "\n".join(lines) + "\n"

    # Compared as bytes, and written as bytes. read_text() applies universal
    # newline translation, so a file holding CRLF reads back as LF and
    # compares equal to freshly generated LF content - the check reported
    # "unchanged" while the bytes on disk differed, and the file was never
    # rewritten. write_text() would translate on the way out too.
    encoded = content.encode()
    if target.exists() and target.read_bytes() == encoded:
        return False
    target.write_bytes(encoded)
    return True


def _lf(value: str) -> str:
    """Normalise line endings to LF, keeping the line breaks themselves.

    Some guide prose arrives with Windows endings. Git rewrites CRLF to LF on
    checkout, so the file on disk would differ from the one the pipeline just
    produced - the idempotency check would see a change every run and rewrite
    it, putting a spurious diff in the pull request every week.

    This is not the same as flattening: paragraphs survive, and the app's CSV
    parser reads them.
    """
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _csv_row(values: list[str]) -> str:
    import io

    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(values)
    return buffer.getvalue()
