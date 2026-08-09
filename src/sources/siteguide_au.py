"""Site Guide AU adapter — versioned bulk export, no API key.

Site Guide nests launches under a site, and *only launches carry
coordinates*: the site is a named area holding the metadata. One record is
emitted per launch, because a launch is the same unit as a PGE record. Most
sites have exactly one launch, but 21 have several - Manilla - Mt Borah has
four (West/East/South/Northeast) where PGE has a single lumped record.

Wind comes from the `conditions` prose (see src/wind.py). It is almost always
site-level - 235 of 245 launches inherit it from their parent, only 26 have
their own - so a launch's own conditions win where present and the parent
fills in otherwise. That matters for sites like Bastion, whose site-level
string "SW-NW, NW-NE" is the union of its two launches' individual ranges.

The published version id is recorded for the run summary, but is *not* used
to skip the download. It was: an unchanged version returned no records, which
silently removed every Site Guide launch from the dataset - including the 135
that exist in no other source - while the health check waved it through
because it exempted "skipped" sources. The export is a single request; the
optimisation was never worth that failure mode.
"""

from __future__ import annotations

import re

import httpx

from src.model import BoundingBox, SiteRecord
from src.wind import parse_conditions

_BASE_URL = "https://siteguide.org.au"
_TIMEOUT = 60.0

# The Tasmanian club publishes placeholder coordinates for some sites and
# keeps the real position for members, so proximity to another source there
# is coincidence, not evidence.
_APPROXIMATE = re.compile(r"available to .*members", re.IGNORECASE)


class SiteGuideAuSource:
    # The provider prefix carried in every `source` token, and so in every
    # ref a device stores. `ansg` is what the guide calls itself - the
    # Australian National Site Guide - and matches the label the app already
    # shows on its per-guide tab. The module keeps its name: this adapter is
    # for siteguide.org.au, the website, not the guide's abbreviation.
    name = "ansg"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT, base_url=_BASE_URL)
        self.current_version_id: int | None = None

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        version = self._client.get("/api/Version")
        version.raise_for_status()
        self.current_version_id = version.json()["id"]

        export = self._client.get("/api/Export")
        export.raise_for_status()
        payload = export.json()
        sites = payload.get("sites", payload) if isinstance(payload, dict) else payload

        records: list[SiteRecord] = []
        for site in sites:
            records.extend(_launch_records(site, bbox))
        return records


_METRES = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*m\b", re.IGNORECASE)
_FEET = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:ft|')", re.IGNORECASE)
_FEET_TO_M = 0.3048


def _parse_height(value) -> float | None:
    """Site Guide's `height` is free text, never a number.

    Every one of the 220 non-null values observed pairs feet with metres in
    some order - "280'/85m asl, 250' agl", "2,450ft / 750m ASL", "55m / 170ft".
    The first metre figure is taken because above-sea-level is conventionally
    listed before above-ground-level, and ASL is what PGE's takeoff_altitude
    means, so the two are comparable. Feet are only used if no metre figure is
    given at all.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value)
    if match := _METRES.search(text):
        return float(match.group(1).replace(",", ""))
    if match := _FEET.search(text):
        return round(float(match.group(1).replace(",", "")) * _FEET_TO_M, 1)
    return None


def _text(value) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _launch_records(site: dict, bbox: BoundingBox) -> list[SiteRecord]:
    # `closed` is free text, not a flag: "November 2025: Currently closed
    # awaiting new site agreement to be finalised with council." It is carried
    # rather than used to drop the record - dropping it left PGE's entries for
    # the same place on the map as ordinary launches, with nothing anywhere to
    # say the site was shut.
    site_closed = _text(site.get("closed"))

    site_name = _text(site.get("name")) or "Unknown site"
    site_conditions = site.get("conditions")
    approximate = bool(_APPROXIMATE.search(site.get("shortLocation") or ""))
    altitude = _parse_height(site.get("height"))
    url = f"{_BASE_URL}/sites/details/{site['id']}"

    records: list[SiteRecord] = []
    for launch in site.get("launches") or []:
        lat, lon = launch.get("lat"), launch.get("lon")
        if lat is None or lon is None:
            continue
        if not (bbox.south <= lat <= bbox.north and bbox.west <= lon <= bbox.east):
            continue

        launch_name = _text(launch.get("name"))
        # Launch names are often generic ("Main launch", "Launch 1"), which
        # only means something beside the site it belongs to.
        name = f"{site_name} - {launch_name}" if launch_name else site_name

        directions = parse_conditions(_text(launch.get("conditions")) or site_conditions)

        records.append(
            SiteRecord(
                provider="ansg",
                id=f"{site['id']}-{launch['id']}",
                name=name,
                role="launch",
                lat=float(lat),
                lon=float(lon),
                wind={d: 1 for d in sorted(directions)},
                altitude=altitude,
                country="AU",
                url=url,
                # A launch can be shut while its site is open, and vice versa.
                closed=_text(launch.get("closed")) or site_closed,
                approximate_location=approximate,
                group_id=str(site["id"]),
            )
        )
    return records
