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

from src.model import DIRECTIONS, CanonicalSite, ref_for

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
#  ansg:106-28 -> siteguide.org.au/sites/details/106).
CSV_COLUMNS = [
    "id",
    # The key a device stores against a flown site. Emitted rather than left for
    # the app to derive, so one side decides. Appended at the end would read
    # better in a diff, but the app parses by column name, so position is free
    # and next to `id` is where a reader looks for identity.
    "ref",
    "name",
    "longitude",
    "latitude",
    "altitude",
    "country",
    *(f"wind_{d.lower()}" for d in DIRECTIONS),
    "source",
    "closed",
    # "launch" or "landing". Appended rather than slotted in beside `name`,
    # because the app validates the header as a set and parses by name - so a
    # new column is free wherever it goes, and the end keeps the diff readable.
    "site_type",
    # 1 if this launch is a winch or tow field.
    "tow",
    # Which site the row belongs to, as `provider:parentId` tokens in the same
    # `;`-separated form as `source`. This is how a landing finds its launches;
    # distance cannot do it (median gap 1.7km).
    "site_group",
    # What a guide says about a landing, verbatim. Empty for launches: their
    # prose is long, and is looked up live when a site is opened.
    "notes",
    # Which guide's record this row's name, wind and position were taken from.
    #
    # Emitted because a consumer showing a merged row alongside the guides that
    # contributed it cannot otherwise say whose figures it is showing. The app
    # gives each guide a tab and used to introduce the catalogue's values as
    # "this launch as DHV records it", which was unbackable: `source` says which
    # guides describe the launch, not which one won.
    #
    # Read it for exactly what selection means by it - name, wind and position.
    # `altitude` and `notes` gap-fill from a losing guide when the winner
    # published none, so this does not license "every field here is DHV's".
    #
    # Never blank: a single-source row is primary to its only guide.
    "primary",
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


def read_published(path: Path | None = None) -> list:
    """The catalogue already published, for the publish gates to compare against.

    Read before anything is overwritten, so a run can be stopped for replacing a
    good catalogue with a broken one. Reading prior state to *check* a run is
    fine; the ids and keys themselves stay a pure function of the sources, so a
    lost snapshot degrades this to "nothing to compare" rather than renumbering
    everything.

    A snapshot predating the `ref` column is keyed by the same rule that produced
    it, via `ref_for`, so an older file still gives usable comparisons.
    """
    from src.run_summary import PublishedSite

    target = path or APP_CSV
    if not target.exists():
        return []

    published = []
    for row in csv.DictReader(target.read_text().splitlines()):
        tokens = [t for t in (row.get("source") or "").split(";") if t]
        sources = {}
        for token in tokens:
            provider, _, source_id = token.partition(":")
            if provider and source_id:
                sources[provider] = source_id
        if not sources:
            continue
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        published.append(
            PublishedSite(
                ref=row.get("ref") or ref_for(sources),
                lat=lat,
                lon=lon,
                providers=frozenset(sources),
                # A snapshot predating the column held launches and nothing
                # else, so its absence is an answer rather than a gap.
                role=row.get("site_type") or "launch",
            )
        )
    return published


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
            site.ref,
            _lf(site.name),
            f"{site.lon:.6f}",
            f"{site.lat:.6f}",
            "" if site.altitude is None else f"{site.altitude:.0f}",
            (site.country or "").lower(),
            *(str(site.wind.get(d, 0)) for d in DIRECTIONS),
            ";".join(f"{p}:{i}" for p, i in sorted(site.sources.items())),
            _lf(site.closed or ""),
            site.role,
            "1" if site.tow else "0",
            ";".join(site.group),
            _lf(site.notes or ""),
            site.primary,
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
