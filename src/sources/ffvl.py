"""FFVL — Fédération Française de Vol Libre adapter.

The French national authority publishes every site it knows as one JSON file -
launches and landings of one terrain grouped by the terrain's own id, wind arcs
per launch, and DOM-TOM coverage in the same file. It is the guide France's
pilots read, and the one the app's French catalogue should come from.

**The file sits behind an API key.** `data.ffvl.fr/json/sites.json` now answers
with a short notice instead of data; a key is requested per application from
`informatique@ffvl.fr`, and requests have been suspended at times. The app's
weather `FFVL_API_KEY` (balise beacons) is a different credential and does not
unlock this file. So the key arrives through the environment and the run fails
loudly rather than shipping nothing: a body that is not the sites list raises
[FfvlSourceError] instead of parsing to an empty catalogue, because zero
records reads as an outage to the health gate while a gate notice is not an
outage - it is a configuration the run cannot recover from. The exact query
parameter spelling is unconfirmed until a key is granted, so it lives in one
constant, `_KEY_PARAM`. Publish runs fetch live; `FFVL_SITES_PATH` exists for
offline calibration and tests, and is never set on a publish run.

Two ids and what they are for. `id` is the *terrain* - the place one page
describes, holding launches and landings alike - so it is what `group_ids`
carries and what the site page is built from. `numero` names one launch or
landing within the terrain (`73D050A`: department, D=décollage/A=atterrissage,
sequence) and is the record's own key - except one upstream collision (two
Corsican terrains answer to the same numero), where keeping either record would
key two launches alike, so both are dropped with a warning.

Landings carry `vent_favo` too; only launches get wind, mirroring selection's
rule that landing wind is zeroed anyway.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx

from src.model import BoundingBox, Coverage, SiteRecord

LOGGER = logging.getLogger(__name__)

_SITES_URL = "https://data.ffvl.fr/json/sites.json"
_TIMEOUT = 120.0

#: The key's name in the query string, and in the environment. FFVL has not
#: granted a key yet - the request is in with informatique@ffvl.fr - so the
#: parameter spelling is a placeholder until it is, and is isolated here for
#: the day it is confirmed.
_KEY_PARAM = "apikey"
_KEY_ENV = "FFVL_API_KEY"
#: Read the payload from a file instead of the network. Offline calibration
#: and the test suite use it; a publish run never does.
_OFFLINE_ENV = "FFVL_SITES_PATH"


class FfvlSourceError(RuntimeError):
    """FFVL answered, but not with site data - most often the key-gate notice."""


# One box per place FFVL publishes sites, sized round the data itself (the
# 2022-12 export) with margin, not round administrative borders. St Barthélemy
# and St Martin share the 971 postcode and sit inside the Antilles box; they
# publish as `gp` - accepted, since the catalogue has no finer shard for them.
# St-Pierre-et-Miquelon (975) and Wallis-et-Futuna (986) are mapped in
# `_COUNTRIES` but had no flying sites in 2022 and get no box; if FFVL starts
# publishing there the record counts will say so before any merge is affected.
_BBOX_METROPOLE = BoundingBox(south=41.5, west=-5.2, north=51.5, east=9.9)
_BBOX_ANTILLES = BoundingBox(south=14.0, west=-63.5, north=18.4, east=-60.5)
_BBOX_GUYANE = BoundingBox(south=2.0, west=-55.0, north=6.5, east=-50.5)
_BBOX_REUNION = BoundingBox(south=-21.6, west=55.0, north=-20.6, east=56.0)
_BBOX_POLYNESIE = BoundingBox(south=-18.2, west=-153.2, north=-16.2, east=-148.6)
_BBOX_NOUVELLE_CALEDONIE = BoundingBox(south=-23.2, west=163.8, north=-19.8, east=168.2)

#: A single box round all of these would swallow Australia; the pipeline skips
#: a source when no box overlaps the run's scope.
DOM_BBOXES = (
    _BBOX_METROPOLE,
    _BBOX_ANTILLES,
    _BBOX_GUYANE,
    _BBOX_REUNION,
    _BBOX_POLYNESIE,
    _BBOX_NOUVELLE_CALEDONIE,
)


class FfvlSource:
    name = "ffvl"
    label = "FFVL"
    full_name = "Fédération Française de Vol Libre"
    #: The federation's front door. The sites list itself lives on
    #: `data.ffvl.fr`; a site page is below - see `site_url_template`.
    homepage = "https://federation.ffvl.fr/"
    #: `{id}` is the `ffvl:` id in the row's `site_group`: the terrain. One page
    #: per terrain covers its launches and landings alike, so the record's own
    #: `numero` never appears in a URL.
    site_url_template = "https://federation.ffvl.fr/sites_pratique/voir/{id}"
    #: FFVL publishes no terms with the sites export. The key application asks
    #: for them; until they are stated, blank is the honest answer - the same
    #: precedent as DHV. See the README's licensing section.
    licence = ""
    licence_url = ""
    #: The métropole plus the overseas collectivities that fly - a tuple, not a
    #: box, because one box round all of them would span half the planet.
    bbox: Coverage = DOM_BBOXES

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def fetch(self, bbox: Coverage) -> list[SiteRecord]:
        return parse_sites(self._payload(), bbox)

    def _payload(self) -> str:
        path = os.environ.get(_OFFLINE_ENV)
        if path:
            return Path(path).read_text(encoding="utf-8")
        params = {_KEY_PARAM: key} if (key := os.environ.get(_KEY_ENV)) else {}
        response = self._client.get(_SITES_URL, params=params)
        response.raise_for_status()
        return response.text


#: A record is kept iff it names one of these practices, whatever else it also
#: names - the types are about the place, the practices are about what you do
#: there. Kite and speed-riding-only sites drop here, ~9% of the file.
_KEPT_PRACTICES = frozenset({"parapente", "delta"})

#: `site_sous_type` -> (role, is a tow field). FFVL states the type of every
#: record, which is what makes this source richer than PGE for France.
#: Décollage, pente-école and ski domains are places you launch from; a winch
#: platform is a launch you are towed from; an interdiction stays in the
#: catalogue with `closed` set, so the place is not silently missing from the
#: map while the other guides' entries for it keep looking ordinary.
_SHAPE = {
    "Décollage": ("launch", False),
    "Pente école": ("launch", False),
    "Domaine skiable": ("launch", False),
    "Plateforme de treuil": ("launch", True),
    "Atterrissage": ("landing", False),
    "Interdiction de pratique": ("launch", False),
}

#: French 8-point compass -> the app's `DIRECTIONS`. FFVL writes O for West,
#: and one record separates with commas rather than semicolons - both accepted.
_WIND_TOKENS = {
    "N": "N", "NE": "NE", "E": "E", "SE": "SE",
    "S": "S", "SO": "SW", "O": "W", "NO": "NW",
}

#: Postcode prefix -> country for the overseas collectivities. Everything else
#: that is not 97x/98x/99x is metropolitan France, Corsica included, and 99x
#: (Monaco's 980 included) maps to no country this catalogue publishes.
#: St Barthélemy and St Martin share 971 with Guadeloupe and publish as `gp` -
#: the catalogue has no finer shard, and a row keyed to the right coordinates
#: matters more than one to the right two letters.
_COUNTRIES = {
    "971": "GP", "972": "MQ", "973": "GF", "974": "RE", "975": "PM",
    "976": "YT", "986": "WF", "987": "PF", "988": "NC",
}

_WIND_SEPARATORS = re.compile(r"[;,]")


def parse_sites(text: str, bbox: Coverage) -> list[SiteRecord]:
    """Every site in `text` kept by the practice filter and inside `bbox`.

    Module-level so tests never fetch. Raises [FfvlSourceError] when the body
    is not the sites list.
    """
    payload = _decode(text)
    boxes = _boxes(bbox)

    kept: list[SiteRecord] = []
    terrain_of: dict[str, str] = {}
    colliding: set[str] = set()
    for row in payload:
        record = _parse_record(row, boxes)
        if record is None:
            continue
        seen = terrain_of.setdefault(record.id, record.group_ids[0])
        if seen != record.group_ids[0]:
            # The same numero answers to two terrains upstream - the one known
            # collision in the file. Keeping either would key two launches
            # alike, which no ref may do; both go, loudly.
            colliding.add(record.id)
            continue
        kept.append(record)

    if colliding:
        LOGGER.warning(
            "ffvl: numero(s) %s name more than one terrain each - dropping all "
            "their records, a key shared by two launches is not a key",
            ", ".join(sorted(colliding)),
        )
    return [r for r in kept if r.id not in colliding]


def _decode(text: str) -> list:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise _gate_error(text) from error
    if not isinstance(payload, list):
        raise _gate_error(text)
    return payload


def _gate_error(text: str) -> FfvlSourceError:
    excerpt = " ".join(text.split())[:120]
    return FfvlSourceError(
        "FFVL answered with something that is not the sites file - most often "
        f"the key-gate notice: {excerpt!r}. The bulk export needs an API key "
        "per application (informatique@ffvl.fr); set FFVL_API_KEY so the fetch "
        "sends it, and never fall back to a cached file to publish from."
    )


def _boxes(bbox: Coverage) -> tuple[BoundingBox, ...]:
    # A BoundingBox *is* a tuple, so the check is for the named kind first.
    return (bbox,) if isinstance(bbox, BoundingBox) else tuple(bbox)


def _parse_record(row: dict, boxes: tuple[BoundingBox, ...]) -> SiteRecord | None:
    practices = {p.strip() for p in (row.get("pratiques") or "").split(";")}
    if not practices & _KEPT_PRACTICES:
        return None

    sous_type = (row.get("site_sous_type") or "").strip()
    shape = _SHAPE.get(sous_type)
    if shape is None:
        LOGGER.warning(
            "ffvl: %r has sous-type %r with no role mapping - dropped",
            row.get("numero") or row.get("suid"), sous_type,
        )
        return None
    role, tow = shape

    numero = (row.get("numero") or "").strip()
    terrain = (row.get("id") or "").strip()
    if not numero or not terrain:
        LOGGER.warning(
            "ffvl: %r publishes neither a numero nor a terrain id - dropped, "
            "a record with no key cannot be stored or linked",
            (row.get("nom") or "").strip() or row.get("suid"),
        )
        return None

    try:
        lat, lon = float(row.get("lat")), float(row.get("lon"))
    except (TypeError, ValueError):
        return None
    if not any(b.south <= lat <= b.north and b.west <= lon <= b.east for b in boxes):
        return None

    country = _country((row.get("cp") or "").strip())
    if country is None:
        LOGGER.warning(
            "ffvl: %s has postcode %r that maps to no country this catalogue "
            "publishes - dropped", numero, row.get("cp"),
        )
        return None

    wind: dict[str, int] = {}
    if role == "launch":
        for raw in _WIND_SEPARATORS.split(row.get("vent_favo") or ""):
            direction = _WIND_TOKENS.get(raw.strip().upper())
            if direction is None:
                if raw.strip():
                    LOGGER.warning(
                        "ffvl: %s has an unknown wind token %r - ignored",
                        numero, raw.strip(),
                    )
                continue
            wind[direction] = 1

    try:
        altitude = float(row.get("alt"))
    except (TypeError, ValueError):
        altitude = None

    closed = None
    if sous_type == "Interdiction de pratique":
        # Only the explicit type closes a site: `restrictions` prose on an
        # ordinary launch is seasonal - falcon-nesting bans and the like -
        # which is not a closure and must not read as one.
        closed = (row.get("restrictions") or "").strip() or \
            "Interdiction de pratique (FFVL)"

    return SiteRecord(
        provider="ffvl",
        id=numero,
        name=_name(row),
        role=role,
        tow=tow,
        lat=lat,
        lon=lon,
        # FFVL publishes an arc, not a grading, so every direction is "in
        # range" - the same accepted loss of PGE's 0/1/2 as the other guides.
        wind=wind,
        altitude=altitude,
        country=country,
        url=FfvlSource.site_url_template.format(id=terrain),
        closed=closed,
        # Launches and landings of one terrain hang from it, the only usable
        # join: the matcher merges at 250m and FFVL's own terrain pages are
        # the authority on what belongs together.
        group_ids=(terrain,),
    )


def _country(cp: str) -> str | None:
    """The country a postcode publishes as, or None for one no shard holds."""
    if not cp:
        return None
    if cp[:2] in ("97", "98", "99"):
        return _COUNTRIES.get(cp[:3])
    return "FR"


def _name(row: dict) -> str:
    nom = (row.get("nom") or "").strip()
    sous_nom = (row.get("sous_nom") or "").strip()
    if not nom:
        return sous_nom
    if sous_nom and sous_nom.lower() != nom.lower():
        return f"{nom} - {sous_nom}"
    return nom
