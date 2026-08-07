"""ParaglidingEarth adapter — public GeoJSON bounding-box endpoint, no API key.

Endpoint and response shape verified against the existing Dart client in
the_paragliding_app (lib/services/paragliding_earth_api.dart), which already
calls this in production. A single request over the whole Australia bounding
box was observed returning far fewer sites than a country that size should
have, so this tiles the requested box into a grid and dedupes results by id
across tile edges rather than trusting one request to return everything.
"""

from __future__ import annotations

import httpx

from src.model import BoundingBox, SiteRecord

_BASE_URL = "https://www.paraglidingearth.com/api/geojson/getBoundingBoxSites.php"
_TIMEOUT = 15.0
_TILE_LIMIT = 500
_LANDING_MARKERS = ("landing", "atterrissage", "landeplatz")
_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


class PgeSource:
    name = "pge"

    def __init__(self, *, grid: int = 4, client: httpx.Client | None = None) -> None:
        self._grid = grid
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        seen: dict[str, SiteRecord] = {}
        for tile in _tiles(bbox, self._grid):
            for record in self._fetch_tile(tile):
                seen[record.id] = record
        return list(seen.values())

    def _fetch_tile(self, tile: BoundingBox) -> list[SiteRecord]:
        response = self._client.get(
            _BASE_URL,
            params={
                "north": tile.north,
                "south": tile.south,
                "east": tile.east,
                "west": tile.west,
                "limit": _TILE_LIMIT,
                "style": "detailled",
            },
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        return [record for f in features if (record := _parse_feature(f)) is not None]


def _tiles(bbox: BoundingBox, grid: int) -> list[BoundingBox]:
    lat_step = (bbox.north - bbox.south) / grid
    lon_step = (bbox.east - bbox.west) / grid
    return [
        BoundingBox(
            south=bbox.south + row * lat_step,
            north=bbox.south + (row + 1) * lat_step,
            west=bbox.west + col * lon_step,
            east=bbox.west + (col + 1) * lon_step,
        )
        for row in range(grid)
        for col in range(grid)
    ]


def _parse_feature(feature: dict) -> SiteRecord | None:
    geometry = feature.get("geometry") or {}
    properties = feature.get("properties") or {}
    coordinates = geometry.get("coordinates")
    if not coordinates or len(coordinates) < 2:
        return None

    lon, lat = coordinates[0], coordinates[1]
    altitude = coordinates[2] if len(coordinates) > 2 else None

    site_id = str(
        feature.get("id") or properties.get("id") or properties.get("_id") or f"{lat:.6f},{lon:.6f}"
    )
    name = str(properties.get("name") or "Unknown site")
    role = "landing" if any(marker in name.lower() for marker in _LANDING_MARKERS) else "launch"

    orientation = frozenset(
        direction for direction in _DIRECTIONS if str(properties.get(direction)) in ("1", "2")
    )

    country_code = properties.get("countryCode")
    country = str(country_code).upper() if country_code else None

    return SiteRecord(
        provider="pge",
        id=site_id,
        name=name,
        role=role,
        lat=float(lat),
        lon=float(lon),
        altitude=float(altitude) if altitude is not None else None,
        orientation=orientation,
        country=country,
        raw=properties,
    )
