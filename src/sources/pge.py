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

from dataclasses import replace

from src.model import DIRECTIONS, WORLD_BBOX, BoundingBox, SiteRecord

_BASE_URL = "https://www.paraglidingearth.com/api/geojson/getBoundingBoxSites.php"
_TIMEOUT = 180.0
_LANDING_MARKERS = ("landing", "atterrissage", "landeplatz")


class PgeSource:
    name = "pge"
    bbox = WORLD_BBOX

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

        records = [r for f in features if (r := _parse_feature(f)) is not None]
        return records + _landing_records(features)


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

    altitude = _text(properties.get("takeoff_altitude"))
    country = _text(properties.get("countryCode"))

    return SiteRecord(
        provider="pge",
        id=site_id,
        name=name,
        role=role,
        lat=lat,
        lon=lon,
        wind=wind,
        altitude=float(altitude) if altitude and altitude.replace(".", "", 1).isdigit() else None,
        country=country.upper() if country else None,
        url=_site_url(properties.get("pge_link"), site_id),
        # Set on 2 of 494 Alpine records and 4 of 508 French ones, so PGE is not
        # a usable source of tow sites on its own - carried anyway, because one
        # guide saying so is enough and DHV cannot speak for France.
        tow=str(properties.get("winch", "0")).strip() == "1",
        # PGE has no notion of a site above a launch, so a launch is its own
        # parent. That is what lets its landing point at it.
        group_ids=(site_id,),
    )


def _landing_records(features: list[dict]) -> list[SiteRecord]:
    """The landings PGE hangs off its takeoffs, as rows of their own.

    PGE publishes no landing records - every feature is a takeoff, and the
    landing is a nested `landing{}` object on it, present for 238 of 494 Alpine
    takeoffs. Turning them into rows is what gives the app landings outside the
    countries a national guide covers; without it a pilot in Spain or Australia
    sees none at all.

    Deduplicated by coordinate, because a landing serving several takeoffs is
    published on each of them: 8 coordinates cover 17 Alpine takeoffs, and the
    Lienz field alone is shared by Zettersfeld, Hochstein and Kollnig. Emitting
    one row per takeoff would draw three windsocks in a field with one.

    The id is the takeoff's with `-lz` appended rather than a `pge-lz:` prefix.
    A new prefix would be a provider absent from the app's `providerPrecedence`,
    which the app now fails a test over; and `getDetailsForCatalogSite` parses a
    PGE id as an integer, so `4632-lz` declines to fetch the takeoff's detail
    blob - which is what a landing should do.
    """
    by_position: dict[tuple[str, str], SiteRecord] = {}

    for feature in features:
        properties = feature.get("properties") or {}
        landing = properties.get("landing")
        if not isinstance(landing, dict):
            continue

        lat, lon = _coordinate(landing.get("landing_lat")), _coordinate(landing.get("landing_lng"))
        if lat is None or lon is None:
            continue

        takeoff_id = _text(properties.get("pge_site_id")) or _text(feature.get("id"))
        if takeoff_id is None:
            continue

        # Rounded to ~1m before comparing: the same field republished under two
        # takeoffs agrees to the digit today, but a later correction to one of
        # them should not silently split the row in two.
        position = (f"{lat:.5f}", f"{lon:.5f}")
        if position in by_position:
            # Already have this field from another takeoff. Record that this
            # takeoff shares it, so the app can join from either.
            existing = by_position[position]
            by_position[position] = replace(
                existing, group_ids=existing.group_ids + (takeoff_id,)
            )
            continue

        altitude = _text(landing.get("landing_altitude"))
        # `landing_name` is absent on 62% of them and is sometimes the literal
        # string "null", so the takeoff's name is the readable fallback.
        landing_name = _text(landing.get("landing_name"))
        if landing_name in (None, "null"):
            takeoff_name = _text(properties.get("name")) or "Unknown site"
            landing_name = f"{takeoff_name} Landing"

        by_position[position] = SiteRecord(
            provider="pge",
            id=f"{takeoff_id}-lz",
            name=landing_name,
            role="landing",
            lat=lat,
            lon=lon,
            altitude=float(altitude) if altitude and altitude.replace(".", "", 1).isdigit() else None,
            country=(_text(properties.get("countryCode")) or "").upper() or None,
            url=_site_url(properties.get("pge_link"), takeoff_id),
            group_ids=(takeoff_id,),
            # Present on 162 of 238 Alpine landings, and the practical half of
            # what PGE knows about one: "huge LZ (with windsocks) just north of
            # mainroad and parking, 5 mins walk to gondola station".
            notes=_text(landing.get("landing_description")),
        )

    return list(by_position.values())


def _coordinate(value) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _site_url(pge_link, site_id: str) -> str:
    """PGE publishes pge_link as http://; the site serves https, and these
    end up as clickable links in a review table."""
    link = _text(pge_link)
    if not link:
        return f"https://www.paraglidingearth.com/?site={site_id}"
    return link.replace("http://", "https://", 1) if link.startswith("http://") else link
