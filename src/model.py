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
GERMANY_BBOX = BoundingBox(south=45.0, west=5.0, north=56.0, east=16.0)


def intersect(a: BoundingBox, b: BoundingBox) -> BoundingBox | None:
    """The area both boxes cover, or None if they do not overlap.

    An adapter declares the extent it publishes and the run declares the extent
    it wants; the fetch is the overlap. None means "this source has nothing to
    say about this run", which is a skip rather than an empty fetch - a source
    that returned zero records would otherwise read as an outage to the health
    gate, which is exactly the confusion `--scope au` used to cause.
    """
    south, west = max(a.south, b.south), max(a.west, b.west)
    north, east = min(a.north, b.north), min(a.east, b.east)
    if south >= north or west >= east:
        return None
    return BoundingBox(south=south, west=west, north=north, east=east)

DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

#: Which guide's id keys a launch described by more than one, most durable
#: first. See `CanonicalSite.ref`.
#:
#: `pge` leads because it is present for ~97% of the catalogue, which keeps one
#: rule working in every country rather than a different key space per national
#: guide. It is deliberately not the same question as which guide's *content*
#: wins - see `selection.NATIONAL_SCOPE` for that.
#:
#: The app carries an identical list as the fallback for a snapshot with no `ref`
#: column. The two must not drift: a launch keyed `pge:` here and `ansg:` there
#: would leave a fresh install and an upgraded one disagreeing about the same
#: site.
#: `dhv` is last because it arrived last, not because it is worth less: a
#: launch both guides describe keeps the `pge:` key devices already store, and
#: re-keying one is a delete plus an insert that takes the pilot's favourite
#: with it.
KEY_PRECEDENCE = ("pge", "ansg", "dhv")


def ref_for(sources: dict[str, str]) -> str:
    """The key for a launch described by `sources`, as `provider:id`.

    Module-level rather than only a property, because a *previous* published
    snapshot arrives as CSV rows rather than CanonicalSite objects and has to be
    keyed by the identical rule - the publish gates compare the two, and a second
    spelling of this would make that comparison meaningless.
    """
    for provider in KEY_PRECEDENCE:
        if provider in sources:
            return f"{provider}:{sources[provider]}"
    # A guide with no ranking yet. Deterministic beats arbitrary: sorted, so two
    # runs over the same cluster agree.
    provider, source_id = sorted(sources.items())[0]
    return f"{provider}:{source_id}"


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
    altitude: float | None = None
    country: str | None = None
    url: str | None = None
    # Why a guide says this launch is shut, verbatim.
    #
    # Closed sites used to be dropped. That left the *other* guides' entries
    # for the same place on the map as ordinary launches with nothing to say
    # it was closed, making the merged dataset less safe than either source
    # alone. Quinns Rocks is the case: the Australian guide has it closed
    # pending a council agreement, PGE has two entries that do not know that,
    # and the app showed only PGE's.
    closed: str | None = None
    # Sites whose published coordinates are deliberately approximate, so
    # proximity to another source is coincidence rather than evidence.
    approximate_location: bool = False
    # The parent this record belongs to within its own source, where the
    # source has that notion. Two launches under one Site Guide site are
    # deliberately distinct, never duplicates of each other.
    group_id: str | None = None

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
    altitude: float | None = None
    country: str | None = None
    url: str | None = None
    #: Set if *any* contributing guide says the launch is shut - one guide
    #: knowing is enough for a pilot to want to know.
    closed: str | None = None

    @property
    def ref(self) -> str:
        """The key the app stores against a flown site, e.g. `pge:4632`.

        A guide's own id, because the canonical id above is ours: it comes from a
        registry in this repository, and when a consumer keys user data on it the
        guarantee lives somewhere the consumer cannot see. A guide's id is
        assigned and maintained upstream, so a catalogue rebuild cannot move it.

        Derived from `sources`, like `numeric_id` is derived from `id`, so it
        cannot drift from the row it describes. The app used to choose this
        itself; emitting it means one authority decides, and the app's fallback
        rule must stay identical to [KEY_PRECEDENCE] until it can be dropped.

        Note this is *not* `primary`. `primary` says whose name and wind won -
        the local guide, inside its own country. This says which id is the most
        durable handle, which is a different question and usually a different
        answer.
        """
        return ref_for(self.sources)

    @property
    def numeric_id(self) -> int:
        """The canonical id as an integer, for the app's INTEGER PRIMARY KEY.

        pge_sites.id and sites.pge_site_id are both INTEGER; migrating those
        column types across every query to carry a "PSF-000001" string would
        be a great deal of churn for a cosmetic prefix. The numeric part is
        derived, stable and reversible, and sites/<cc>.json keeps the readable
        form for review.
        """
        return int(self.id.rsplit("-", 1)[1])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            # Also in the review JSON, because "which id does a device key on"
            # is exactly the sort of thing a human should be able to see change
            # in a pull request.
            "ref": self.ref,
            "name": self.name,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "wind": {d: self.wind[d] for d in DIRECTIONS if self.wind.get(d)},
            "altitude": self.altitude,
            "sources": dict(sorted(self.sources.items())),
            "primary": self.primary,
            "url": self.url,
        }
