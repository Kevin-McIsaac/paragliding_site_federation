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

/api/Version is checked first; an unchanged version id skips the export
download entirely.
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
    name = "siteguide_au"

    def __init__(
        self, *, last_version_id: int | None = None, client: httpx.Client | None = None
    ) -> None:
        self._last_version_id = last_version_id
        self._client = client or httpx.Client(timeout=_TIMEOUT, base_url=_BASE_URL)
        self.current_version_id: int | None = None
        self.skipped_unchanged = False

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        version = self._client.get("/api/Version")
        version.raise_for_status()
        self.current_version_id = version.json()["id"]

        if self._last_version_id is not None and self._last_version_id == self.current_version_id:
            self.skipped_unchanged = True
            return []

        export = self._client.get("/api/Export")
        export.raise_for_status()
        payload = export.json()
        sites = payload.get("sites", payload) if isinstance(payload, dict) else payload

        records: list[SiteRecord] = []
        for site in sites:
            records.extend(_launch_records(site, bbox))
        return records


def _text(value) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _launch_records(site: dict, bbox: BoundingBox) -> list[SiteRecord]:
    if site.get("closed"):
        return []

    site_name = _text(site.get("name")) or "Unknown site"
    site_conditions = site.get("conditions")
    approximate = bool(_APPROXIMATE.search(site.get("shortLocation") or ""))
    url = f"{_BASE_URL}/sites/{site['id']}"

    records: list[SiteRecord] = []
    for launch in site.get("launches") or []:
        if launch.get("closed"):
            continue
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
                provider="siteguide_au",
                id=f"{site['id']}-{launch['id']}",
                name=name,
                role="launch",
                lat=float(lat),
                lon=float(lon),
                wind={d: 1 for d in sorted(directions)},
                country="AU",
                url=url,
                approximate_location=approximate,
            )
        )
    return records
