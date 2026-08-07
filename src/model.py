"""Shared data model used by every source adapter and the matcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple


class BoundingBox(NamedTuple):
    south: float
    west: float
    north: float
    east: float


AUSTRALIA_BBOX = BoundingBox(south=-44.0, west=112.0, north=-10.0, east=154.0)


@dataclass(frozen=True)
class SiteRecord:
    """A single launch/landing point as reported by one source."""

    provider: str
    id: str
    name: str
    role: str  # "launch" or "landing"
    lat: float
    lon: float
    altitude: float | None = None
    orientation: frozenset[str] = field(default_factory=frozenset)
    country: str | None = None
    raw: dict = field(default_factory=dict)
