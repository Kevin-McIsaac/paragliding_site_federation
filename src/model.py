"""Shared data model.

Deliberately narrow. The app's core job is drawing launches on a map, which
needs only name, position, wind directions and a link back to the source -
everything else (altitude, rating, hazards, access notes) is looked up from
the source when a user actually opens a site, so it does not belong in the
bulk table that ships with the app.

`role` and `country` are carried for internal use - gating landings out of
matches, and sharding output by country - not because the app needs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple


class BoundingBox(NamedTuple):
    south: float
    west: float
    north: float
    east: float


WORLD_BBOX = BoundingBox(south=-90.0, west=-180.0, north=90.0, east=180.0)
AUSTRALIA_BBOX = BoundingBox(south=-44.0, west=112.0, north=-10.0, east=154.0)

DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class SiteRecord:
    """One launch as published by one source."""

    provider: str
    id: str
    name: str
    role: str  # "launch" or "landing"
    lat: float
    lon: float
    # direction -> 0 none / 1 good / 2 excellent. Only non-zero entries kept.
    wind: dict[str, int] = field(default_factory=dict)
    country: str | None = None
    url: str | None = None
    # Sites whose published coordinates are deliberately approximate, so
    # proximity to another source is coincidence rather than evidence.
    approximate_location: bool = False

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"


@dataclass(frozen=True)
class CanonicalSite:
    """One launch, backed by one or more sources."""

    id: str
    name: str
    lat: float
    lon: float
    wind: dict[str, int]
    sources: dict[str, str]  # provider -> that source's id
    primary: str
    country: str | None = None
    url: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "wind": {d: self.wind[d] for d in DIRECTIONS if self.wind.get(d)},
            "sources": dict(sorted(self.sources.items())),
            "primary": self.primary,
            "url": self.url,
        }
