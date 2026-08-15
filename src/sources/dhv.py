"""DHV Geländedatenbank adapter — public per-country KML, no API key.

DHV nests *Flächen* (takeoffs, landings, tow fields) under a *Gelände*, and
only the Fläche carries coordinates — the same shape as Site Guide's
site/launch split, so one record is emitted per takeoff.

Three things about this source are worth knowing before changing anything here.

**The KML and GPX exports are public; CSV, XML and TomTom are not.** Those
redirect to the ServicePortal login. KML is the richest of the two open
formats: it types each Fläche through `styleUrl`, which GPX does not.

**There is no per-Fläche id.** Every area of a Gelände shares one `item`
number — Diedamskopf's three takeoffs and two landings are all `item=1219` —
and the "report a change" links show DHV has no finer identifier internally
either. So the ref is the Gelände id plus a slug of the area's own name, which
is the only other handle upstream assigns. Measured over everything this
adapter emits for DE/AT/CH - all 1,832 records, Startplätze and Schleppgelände
alike - every ref is distinct, so no Gelände holds two identically-named areas.
A rename costs one re-key; it can never point at a different launch, which is
the property that matters (see `CatalogRef` in the app).

**Landings are emitted, and joined by the Gelände rather than by distance.**
They cannot be attached geometrically: the median gap from a landing to the
nearest takeoff of its own Gelände is 1,672m, p90 4.2km, and only 9% fall inside
the 250m the matcher merges at. `item=` is the only usable join, and 28.5% of
landings sit under a Gelände holding more than one launch — so a landing belongs
to several launches and cannot be a field on one.

DHV publishes almost nothing about a landing beyond where it is: name, commune,
altitude, and no Startrichtung on any of the 1,318. That is still the answer to
"where am I expected to land", which the app could not give at all before.

Tow fields are launches — a third of the German data, PGE carries almost none of
them, and only 18 of 318 tow Gelände also hold a Startplatz, so treating them as
launches creates no ambiguity with hill sites.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ElementTree

import httpx

from src.model import BoundingBox, SiteRecord
from src.wind import parse_conditions

_BASE_URL = "https://service.dhv.de"
_EXPORT = "/dbfiles/managed/gelaendedaten/kml/dhvgelaende_kml_{country}.kml"
_TIMEOUT = 120.0
_KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

#: `styleUrl` -> whether the Fläche is somewhere you launch from.
#: `styleUrl` -> (role, is a tow field). DHV states the type of every Fläche,
#: which is why this adapter reads the KML rather than the GPX: measured against
#: the KML as truth, GPX's prose markers are missing or wrong for ~14% of
#: launches and for 300 of 355 tow fields.
_STYLES = {
    "dhv_startplatz": ("launch", False),
    "dhv_schlepp": ("launch", True),
    "dhv_landeplatz": ("landing", False),
}

_ITEM = re.compile(r"item=(\d+)")
_WIND = re.compile(r"Startrichtung\s*([^<]*)")
_ALTITUDE = re.compile(r"Höhe NN\s*(-?\d+)\s*m")

# German compass tokens differ from English in one letter: Ost, not East. Every
# token follows from that - NO/SO/NNO/OSO and so on - so the substitution is
# made inside whole tokens rather than over the whole string, which would also
# rewrite an O in a place name.
_COMPASS_TOKEN = re.compile(r"\b[NSOW]{1,3}\b")

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


class DhvSource:
    name = "dhv"
    label = "DHV"
    full_name = "DHV Geländedatenbank"
    #: The browsable index, which is a different address from a site page
    #: below - `db3/gelaende` against `db2/details.php`.
    homepage = "https://service.dhv.de/db3/gelaende"
    #: `{id}` is the `dhv:` id in the row's `site_group`: the Gelände. DHV has
    #: no page per launch - every takeoff and landing on a hill shares one - so
    #: the Gelände is the whole address, and a record's own
    #: `<Gelände>-<slug>` id is this pipeline's key, not DHV's.
    site_url_template = "https://service.dhv.de/db2/details.php?qi=glp_details&item={id}"
    #: DHV publishes no terms with the Geländedaten KML export. Public and
    #: needing no login is not a licence; see the README.
    licence = ""
    licence_url = ""
    #: Germany, Austria and Switzerland - a box round the Alps and north to the
    #: Baltic. DHV publishes files for most of Europe, but thinly outside these
    #: three (~140 French takeoffs against FFVL's ~2,000), where it would add
    #: merge noise rather than coverage.
    bbox = BoundingBox(south=45.0, west=5.0, north=56.0, east=17.5)
    countries = ("de", "at", "ch")

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=_TIMEOUT, base_url=_BASE_URL)

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        records: list[SiteRecord] = []
        for country in self.countries:
            response = self._client.get(_EXPORT.format(country=country))
            response.raise_for_status()
            records += parse_kml(response.text, country.upper(), bbox)
        return records


def _slug(name: str) -> str:
    """A stable, ASCII form of a Fläche name, for the half of the ref DHV
    does not number itself."""
    folded = name.lower().translate(_UMLAUTS)
    ascii_only = (
        unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode()
    )
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_only)).strip("-")


def _to_english_compass(text: str) -> str:
    return _COMPASS_TOKEN.sub(lambda m: m.group(0).replace("O", "E"), text)


def parse_kml(xml: str, country: str, bbox: BoundingBox) -> list[SiteRecord]:
    root = ElementTree.fromstring(xml)
    records: list[SiteRecord] = []
    for placemark in root.iterfind(".//kml:Placemark", _KML_NS):
        record = _parse_placemark(placemark, country, bbox)
        if record is not None:
            records.append(record)
    return records


def _parse_placemark(placemark, country: str, bbox: BoundingBox) -> SiteRecord | None:
    style = (placemark.findtext("kml:styleUrl", "", _KML_NS) or "").lstrip("#")
    if style not in _STYLES:
        return None
    role, tow = _STYLES[style]

    description = placemark.findtext("kml:description", "", _KML_NS) or ""
    item = _ITEM.search(description)
    name = (placemark.findtext("kml:name", "", _KML_NS) or "").strip()
    coordinates = placemark.findtext(".//kml:coordinates", "", _KML_NS) or ""

    # A Fläche with no Gelände id has nothing durable to key on, and one whose
    # name leaves nothing behind after slugging cannot be told from its
    # siblings - two of those under one Gelände would collide on `<item>-`.
    # Either way the ref would not be stable, so the record is dropped rather
    # than given a made-up one. No launch in the current export hits this.
    slug = _slug(name)
    if item is None or not slug:
        return None

    parts = coordinates.strip().split(",")
    if len(parts) < 2:
        return None
    try:
        lon, lat = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (bbox.south <= lat <= bbox.north and bbox.west <= lon <= bbox.east):
        return None

    altitude = _ALTITUDE.search(description)
    wind = _WIND.search(description)
    directions = (
        parse_conditions(_to_english_compass(wind.group(1))) if wind else set()
    )

    return SiteRecord(
        provider="dhv",
        id=f"{item.group(1)}-{slug}",
        name=name,
        role=role,
        tow=tow,
        lat=lat,
        lon=lon,
        # DHV publishes an arc, not a grading, so every direction is "in range"
        # - the same accepted loss of PGE's 0/1/2 as the Australian guide.
        wind={d: 1 for d in sorted(directions)},
        altitude=float(altitude.group(1)) if altitude else None,
        country=country,
        url=f"{_BASE_URL}/db2/details.php?qi=glp_details&item={item.group(1)}",
        # Every Fläche of one Gelände is a deliberate distinction, never a
        # duplicate - so they are never reported as one.
        group_ids=(item.group(1),),
    )
