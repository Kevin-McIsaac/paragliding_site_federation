"""ParaglidingEarth adapter — the whole world in a single request.

`getBoundingBoxSites.php` with a -90/90, -180/180 box returns the complete
dataset (11,437 sites across 137 countries when this was written). Verified
complete rather than truncated by comparing against the per-country endpoint
`getCountrySites.php?iso=au`: 238 vs 239 for Australia. This is the same call
bin/fetch_pge_sites.sh in the app repo has always used to build the bundled
world CSV, so it is well-proven.
"""

from __future__ import annotations

import httpx

from src.model import BoundingBox, SiteRecord

_BASE_URL = "https://www.paraglidingearth.com/api/geojson/getBoundingBoxSites.php"
_TIMEOUT = 120.0
_LANDING_MARKERS = ("landing", "atterrissage", "landeplatz")
_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_FLAGS = ("thermals", "soaring", "xc", "winch", "flatland", "hanggliding", "paragliding")


class PgeSource:
    name = "pge"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        response = self._client.get(
            _BASE_URL,
            params={
                "north": bbox.north,
                "south": bbox.south,
                "east": bbox.east,
                "west": bbox.west,
                "style": "detailled",
            },
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        return [r for f in features if (r := _parse_feature(f)) is not None]


def _num(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result != 0.0 else None


def _text(value) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _parse_feature(feature: dict) -> SiteRecord | None:
    geometry = feature.get("geometry") or {}
    properties = feature.get("properties") or {}
    coordinates = geometry.get("coordinates")
    if not coordinates or len(coordinates) < 2:
        return None

    lon, lat = _num(coordinates[0]), _num(coordinates[1])
    if lat is None or lon is None:
        return None

    site_id = _text(properties.get("pge_site_id")) or _text(feature.get("id"))
    if site_id is None:
        return None

    name = _text(properties.get("name")) or "Unknown site"
    role = "landing" if any(m in name.lower() for m in _LANDING_MARKERS) else "launch"

    orientation = frozenset(d for d in _DIRECTIONS if str(properties.get(d)) in ("1", "2"))
    flags = frozenset(f for f in _FLAGS if str(properties.get(f)) in ("1", "2", "true", "True"))

    country_code = _text(properties.get("countryCode"))

    return SiteRecord(
        provider="pge",
        id=site_id,
        name=name,
        role=role,
        lat=lat,
        lon=lon,
        altitude=_num(properties.get("takeoff_altitude")) or (_num(coordinates[2]) if len(coordinates) > 2 else None),
        country=country_code.upper() if country_code else None,
        orientation=orientation,
        description=_text(properties.get("takeoff_description")),
        landing_lat=_num(properties.get("landing_lat")),
        landing_lon=_num(properties.get("landing_lng")),
        url=_text(properties.get("pge_link")),
        flags=flags,
        raw=properties,
    )
