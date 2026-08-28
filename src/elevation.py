"""Sea-level altitude for a coordinate, from Open-Meteo's Elevation API.

Fills the altitudes no guide states. Site Guide's `height` sometimes only says
how far above the ground a launch sits (issue #8), and for the Australian
launches no other guide describes there is nothing to fall back on - so the
published row would carry no altitude at all. The Copernicus DEM behind
Open-Meteo answers for any coordinate on earth; being a 90 m terrain grid it
reads the hillside rather than the pad, so it is the last choice, not the
first: a figure a guide labelled `asl`/`amsl`, or another guide's curated
takeoff altitude, always wins. Attribution: contains modified Copernicus
atmosphere monitoring service information (DEM GLO-90, CC BY 4.0), fetched via
Open-Meteo - see README.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

LOGGER = logging.getLogger(__name__)

_URL = "https://api.open-meteo.com/v1/elevation"
#: Open-Meteo caps one request at 100 coordinates. The export fits in one
#: request today; the split is here so a growing one cannot grow past it.
_BATCH = 100
_TIMEOUT = 30.0
_OFFLINE_ENV = "OPEN_METEO_ELEVATION_PATH"

Coordinate = tuple[float, float]  # (lat, lon)


def amsl_for_coordinates(
    coords: list[Coordinate], *, client: httpx.Client | None = None
) -> dict[Coordinate, float]:
    """AMSL in metres for each (lat, lon), keyed back by the same tuples.

    Coordinates the API could not answer for are simply absent from the
    result - the caller decides what a missing altitude means. A wholly
    failed call returns {}, which is the label-only behaviour the pipeline
    had before this module existed.
    """
    if not coords:
        return {}
    try:
        elevations = [
            elevation
            for start in range(0, len(coords), _BATCH)
            for elevation in _fetch_batch(coords[start:start + _BATCH], client)
        ]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
        LOGGER.warning("elevation lookup failed, altitudes stay absent: %s", error)
        return {}
    return dict(zip(coords, elevations))


def _fetch_batch(
    batch: list[Coordinate], client: httpx.Client | None
) -> list[float]:
    path = os.environ.get(_OFFLINE_ENV)
    if path:
        # The seam answers a batch from a saved response, keyed by the same
        # "lat,lon" strings the live API is queried with.
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        return [float(saved[f"{lat},{lon}"]) for lat, lon in batch]
    # Open-Meteo's batch form repeats the parameter: latitude=a&longitude=b
    # &latitude=c&longitude=d. Coordinate order in, elevation order out.
    params = [
        (name, value)
        for lat, lon in batch
        for name, value in (("latitude", lat), ("longitude", lon))
    ]
    response = (client or httpx.Client(timeout=_TIMEOUT)).get(_URL, params=params)
    response.raise_for_status()
    elevations = response.json()["elevation"]
    if len(elevations) != len(batch):
        raise ValueError(
            f"elevation API returned {len(elevations)} values "
            f"for {len(batch)} coordinates"
        )
    return [float(value) for value in elevations]