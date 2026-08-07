"""ParaglidingEarth adapter — the whole world in a single request.

`getBoundingBoxSites.php` over a -90/90, -180/180 box returns the complete
dataset (11,508 sites across 136 countries when this was written), verified
complete rather than truncated against the per-country endpoint
`getCountrySites.php?iso=au`. This is the call bin/fetch_pge_sites.sh in the
app repo has always used to build the bundled world CSV.

PGE models one record per takeoff, which is the same unit as a Site Guide
*launch* - a hill with several launches appears as several PGE records
("Long Reef NE", "Long Reef SE", "Long Reef Northfacing").
"""

from __future__ import annotations

import httpx

from src.model import DIRECTIONS, BoundingBox, SiteRecord

_BASE_URL = "https://www.paraglidingearth.com/api/geojson/getBoundingBoxSites.php"
_TIMEOUT = 180.0
_LANDING_MARKERS = ("landing", "atterrissage", "landeplatz")


class PgeSource:
    name = "pge"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        response = self._client.get(
            _BASE_URL,
            params={
                "north": bbox.north, "south": bbox.south,
                "east": bbox.east, "west": bbox.west,
                "style": "detailled",
            },
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        return [r for f in features if (r := _parse_feature(f)) is not None]


def _text(value) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _parse_feature(feature: dict) -> SiteRecord | None:
    geometry = feature.get("geometry") or {}
    properties = feature.get("properties") or {}
    coordinates = geometry.get("coordinates")
    if not coordinates or len(coordinates) < 2:
        return None

    try:
        lon, lat = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return None

    site_id = _text(properties.get("pge_site_id")) or _text(feature.get("id"))
    if site_id is None:
        return None

    name = _text(properties.get("name")) or "Unknown site"
    role = "landing" if any(m in name.lower() for m in _LANDING_MARKERS) else "launch"

    # PGE grades each direction 0 none / 1 good / 2 excellent - the gradation
    # the app's sites table already stores.
    wind = {}
    for direction in DIRECTIONS:
        raw = str(properties.get(direction, "0")).strip()
        if raw in ("1", "2"):
            wind[direction] = int(raw)

    country = _text(properties.get("countryCode"))

    return SiteRecord(
        provider="pge",
        id=site_id,
        name=name,
        role=role,
        lat=lat,
        lon=lon,
        wind=wind,
        country=country.upper() if country else None,
        url=_text(properties.get("pge_link")) or f"https://www.paraglidingearth.com/?site={site_id}",
    )
