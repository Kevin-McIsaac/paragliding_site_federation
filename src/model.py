"""Shared data model: per-source records and the merged canonical site."""

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

# Scalar fields carried through selection and gap-fill, in serialization order.
MERGED_FIELDS = (
    "name",
    "lat",
    "lon",
    "altitude",
    "country",
    "role",
    "orientation",
    "description",
    "hazards",
    "access",
    "rating",
    "landing_lat",
    "landing_lon",
    "url",
    "flags",
)


@dataclass(frozen=True)
class SiteRecord:
    """A single launch as reported by one source, mapped to the shared schema."""

    provider: str
    id: str
    name: str
    role: str  # "launch" or "landing"
    lat: float
    lon: float
    altitude: float | None = None
    country: str | None = None
    orientation: frozenset[str] = frozenset()
    description: str | None = None
    hazards: str | None = None
    access: str | None = None
    rating: str | None = None
    landing_lat: float | None = None
    landing_lon: float | None = None
    url: str | None = None
    flags: frozenset[str] = frozenset()
    raw: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"


@dataclass(frozen=True)
class CanonicalSite:
    """One physical launch, backed by one or more source records."""

    id: str
    sources: dict[str, str]  # provider -> that source's id
    primary: str  # provider whose record was selected
    values: dict  # the MERGED_FIELDS, post selection + gap-fill
    field_sources: dict[str, str]  # field -> provider, only where gap-filled

    def to_dict(self) -> dict:
        record = {
            "id": self.id,
            "sources": dict(sorted(self.sources.items())),
            "primary": self.primary,
        }
        record.update(self.values)
        if self.field_sources:
            record["field_sources"] = dict(sorted(self.field_sources.items()))
        return record
