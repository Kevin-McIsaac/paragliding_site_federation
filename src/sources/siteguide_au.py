"""Site Guide AU adapter — versioned bulk export, no API key.

Verified live: GET /api/Version returns {"id", "publishedTime", "comment"}.
/api/Version is checked first; if its id is unchanged since the last run
(tracked in state/last_run.json), the full /api/Export fetch is skipped
entirely rather than re-downloading an unchanged dataset every run.

/api/Export's exact top-level wrapper key wasn't directly observed (only the
schema was, via swagger) — this defensively accepts either a top-level "sites"
list or a bare list at the root, and should be confirmed on the first real
dry run per the build plan.
"""

from __future__ import annotations

import httpx

from src.model import BoundingBox, SiteRecord

_BASE_URL = "https://siteguide.org.au"
_TIMEOUT = 30.0


class SiteGuideAuSource:
    name = "siteguide_au"

    def __init__(self, *, last_version_id: int | None = None, client: httpx.Client | None = None) -> None:
        self._last_version_id = last_version_id
        self._client = client or httpx.Client(timeout=_TIMEOUT, base_url=_BASE_URL)
        self.current_version_id: int | None = None
        self.skipped_unchanged = False

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        version_response = self._client.get("/api/Version")
        version_response.raise_for_status()
        self.current_version_id = version_response.json()["id"]

        if self._last_version_id is not None and self._last_version_id == self.current_version_id:
            self.skipped_unchanged = True
            return []

        export_response = self._client.get("/api/Export")
        export_response.raise_for_status()
        export = export_response.json()
        sites = export.get("sites", export) if isinstance(export, dict) else export

        records: list[SiteRecord] = []
        for site in sites:
            records.extend(_launch_records(site, bbox))
        return records


def _launch_records(site: dict, bbox: BoundingBox) -> list[SiteRecord]:
    if site.get("closed"):
        return []

    records: list[SiteRecord] = []
    for launch in site.get("launches") or []:
        if launch.get("closed"):
            continue
        lat, lon = launch.get("lat"), launch.get("lon")
        if lat is None or lon is None:
            continue
        if not (bbox.south <= lat <= bbox.north and bbox.west <= lon <= bbox.east):
            continue

        records.append(
            SiteRecord(
                provider="siteguide_au",
                id=f"{site['id']}-{launch['id']}",
                name=launch.get("name") or site.get("name") or "Unknown site",
                role="launch",
                lat=float(lat),
                lon=float(lon),
                altitude=site.get("height"),
                orientation=frozenset(),
                country="AU",
                raw={"site": site, "launch": launch},
            )
        )
    return records
