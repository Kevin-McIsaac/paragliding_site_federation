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

The published version id is recorded for the run summary, but is *not* used
to skip the download. It was: an unchanged version returned no records, which
silently removed every Site Guide launch from the dataset - including the 135
that exist in no other source - while the health check waved it through
because it exempted "skipped" sources. The export is a single request; the
optimisation was never worth that failure mode.
"""

from __future__ import annotations

import re

import httpx

from src.model import AUSTRALIA_BBOX, BoundingBox, SiteRecord
from src.wind import parse_conditions

_BASE_URL = "https://siteguide.org.au"
_TIMEOUT = 60.0

# The Tasmanian club publishes placeholder coordinates for some sites and
# keeps the real position for members, so proximity to another source there
# is coincidence, not evidence.
_APPROXIMATE = re.compile(r"available to .*members", re.IGNORECASE)


class SiteGuideAuSource:
    # The provider prefix carried in every `source` token, and so in every
    # ref a device stores. `ansg` is what the guide calls itself - the
    # Australian National Site Guide - and matches the label the app already
    # shows on its per-guide tab. The module keeps its name: this adapter is
    # for siteguide.org.au, the website, not the guide's abbreviation.
    name = "ansg"
    bbox = AUSTRALIA_BBOX

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT, base_url=_BASE_URL)
        self.current_version_id: int | None = None

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        version = self._client.get("/api/Version")
        version.raise_for_status()
        self.current_version_id = version.json()["id"]

        export = self._client.get("/api/Export")
        export.raise_for_status()
        payload = export.json()
        sites = payload.get("sites", payload) if isinstance(payload, dict) else payload

        records: list[SiteRecord] = []
        for site in sites:
            records.extend(_launch_records(site, bbox))

        shapes = payload.get("mapShapes", []) if isinstance(payload, dict) else []
        records.extend(_landing_records(sites, shapes, bbox))
        return records


def _landing_records(
    sites: list[dict], shapes: list[dict], bbox: BoundingBox
) -> list[SiteRecord]:
    """Landings, from the `mapShapes` polygons the site guide draws them as.

    Site Guide is the only guide here that publishes a landing as an *area*
    rather than a point - 149 shapes in category `Landing`, attached to a site
    through its `mapShapeIds`. The centroid is taken as the point, which is a
    fair answer to "where is the field" for a paddock a few hundred metres
    across, and the only one the app's map can draw.

    Only shapes some site references are emitted. 35 are referenced by nothing,
    and a landing with no launch cannot be reached from the launch page that is
    the whole point of carrying it - a marker with no context is not worth the
    row. 29 shapes are referenced by more than one site, so a landing can carry
    several parents.

    The richer thing Site Guide publishes about landings is prose, on the site
    rather than the shape - `landing` free text on 125 of 244 sites, with real
    rules in it. That is deliberately not carried yet: the catalogue holds no
    prose at all today, and the decision to start belongs with the column that
    would hold it rather than with this parser.
    """
    parents: dict[int, list[str]] = {}
    for site in sites:
        for shape_id in site.get("mapShapeIds") or []:
            parents.setdefault(shape_id, []).append(str(site["id"]))

    records: list[SiteRecord] = []
    for shape in shapes:
        category = (shape.get("category") or {}).get("name")
        if category != "Landing":
            continue
        shape_id = shape.get("id")
        if shape_id not in parents:
            continue

        centroid = _centroid(shape.get("coordinatesList") or [])
        if centroid is None:
            continue
        lat, lon = centroid
        if not (bbox.south <= lat <= bbox.north and bbox.west <= lon <= bbox.east):
            continue

        site_ids = parents[shape_id]
        records.append(
            SiteRecord(
                provider="ansg",
                id=f"lz-{shape_id}",
                name=_text(shape.get("name")) or "Landing",
                role="landing",
                lat=lat,
                lon=lon,
                country="AU",
                url=f"{_BASE_URL}/sites/details/{site_ids[0]}",
                group_ids=tuple(site_ids),
            )
        )
    return records


def _centroid(coordinates_list: list[str]) -> tuple[float, float] | None:
    """The middle of a polygon's outer ring, as (lat, lon).

    The mean of the vertices rather than the area centroid: a landing paddock is
    small enough that the two agree to within metres, and the mean cannot be
    thrown by a degenerate ring the way the area formula can.
    """
    if not coordinates_list:
        return None
    points = []
    for pair in str(coordinates_list[0]).split():
        lon, _, lat = pair.partition(",")
        try:
            points.append((float(lat), float(lon)))
        except ValueError:
            continue
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


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


def _text(value) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def _launch_records(site: dict, bbox: BoundingBox) -> list[SiteRecord]:
    # `closed` is free text, not a flag: "November 2025: Currently closed
    # awaiting new site agreement to be finalised with council." It is carried
    # rather than used to drop the record - dropping it left PGE's entries for
    # the same place on the map as ordinary launches, with nothing anywhere to
    # say the site was shut.
    site_closed = _text(site.get("closed"))

    site_name = _text(site.get("name")) or "Unknown site"
    site_conditions = site.get("conditions")
    approximate = bool(_APPROXIMATE.search(site.get("shortLocation") or ""))
    altitude = _parse_height(site.get("height"))
    url = f"{_BASE_URL}/sites/details/{site['id']}"

    records: list[SiteRecord] = []
    for launch in site.get("launches") or []:
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
                provider="ansg",
                id=f"{site['id']}-{launch['id']}",
                name=name,
                role="launch",
                lat=float(lat),
                lon=float(lon),
                wind={d: 1 for d in sorted(directions)},
                altitude=altitude,
                country="AU",
                url=url,
                # A launch can be shut while its site is open, and vice versa.
                closed=_text(launch.get("closed")) or site_closed,
                approximate_location=approximate,
                group_ids=(str(site["id"]),),
            )
        )
    return records
