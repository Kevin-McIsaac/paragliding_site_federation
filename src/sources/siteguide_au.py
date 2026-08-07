"""Site Guide AU adapter — versioned bulk export, no API key.

/api/Version is checked first; if its id is unchanged since the last run the
full /api/Export download is skipped. Verified live: Version returns
{"id", "publishedTime", "comment"}.

Site Guide models one site as a parent record with several child launches;
each launch becomes its own SiteRecord, since a launch is what actually gets
matched against a PGE site. Descriptive text (hazards, access, rating) lives
on the parent and is inherited by every launch under it.

Note this source carries no wind-orientation data at all. That is exactly why
selection gap-fills from PGE - see src/selection.py.
"""

from __future__ import annotations

import re

import httpx

from src.model import BoundingBox, SiteRecord

_BASE_URL = "https://siteguide.org.au"
_TIMEOUT = 60.0


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
    stripped = str(value).strip()
    return stripped or None


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


def _join(*parts) -> str | None:
    kept = [_text(p) for p in parts]
    kept = [p for p in kept if p]
    return "\n\n".join(kept) if kept else None


def _launch_records(site: dict, bbox: BoundingBox) -> list[SiteRecord]:
    if site.get("closed"):
        return []

    hazards = _join(site.get("hazardsComments"), site.get("flightComments"))
    access = _join(site.get("restrictions"), site.get("landowners"), site.get("shortLocation"))
    rating = _text(site.get("rating"))
    altitude = _parse_height(site.get("height"))

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
                name=_text(launch.get("name")) or _text(site.get("name")) or "Unknown site",
                role="launch",
                lat=float(lat),
                lon=float(lon),
                altitude=altitude,
                country="AU",
                orientation=frozenset(),
                description=_join(launch.get("description"), site.get("description")),
                hazards=hazards,
                access=access,
                rating=rating,
                url=f"{_BASE_URL}/sites/{site['id']}",
                raw={"site_id": site.get("id"), "launch_id": launch.get("id")},
            )
        )
    return records
