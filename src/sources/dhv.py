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
is the only other handle upstream assigns. Measured over the whole DE/AT/CH
export: 1,476 takeoffs, no Gelände holding two identically-named ones, so this
is unique. A rename costs one re-key; it can never point at a different launch,
which is the property that matters (see `CatalogRef` in the app).

**Landings are dropped.** The catalogue's unit is a launch, and the guides it
already federates carry landing coordinates as an attribute of a takeoff rather
than as a row of their own. Emitting them would add ~1,300 rows the app would
draw as launchable sites. Tow fields are kept — they are places you take off
from, they are a third of the German data, and PGE carries almost none of them.
"""

from __future__ import annotations

import re
import unicodedata

import httpx

from src.model import BoundingBox, SiteRecord
from src.wind import parse_conditions

_BASE_URL = "https://service.dhv.de"
_EXPORT = "/dbfiles/managed/gelaendedaten/kml/dhvgelaende_kml_{country}.kml"
_TIMEOUT = 120.0
_KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

#: `styleUrl` -> whether the Fläche is somewhere you launch from.
_LAUNCH_STYLES = ("dhv_startplatz", "dhv_schlepp")

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
    # Imported here so a malformed export raises from the parse rather than at
    # import time, and so the module stays importable without lxml installed.
    import xml.etree.ElementTree as ElementTree

    root = ElementTree.fromstring(xml)
    records: list[SiteRecord] = []
    for placemark in root.iterfind(".//kml:Placemark", _KML_NS):
        record = _parse_placemark(placemark, country, bbox)
        if record is not None:
            records.append(record)
    return records


def _parse_placemark(placemark, country: str, bbox: BoundingBox) -> SiteRecord | None:
    style = (placemark.findtext("kml:styleUrl", "", _KML_NS) or "").lstrip("#")
    if style not in _LAUNCH_STYLES:
        return None

    description = placemark.findtext("kml:description", "", _KML_NS) or ""
    item = _ITEM.search(description)
    name = (placemark.findtext("kml:name", "", _KML_NS) or "").strip()
    coordinates = placemark.findtext(".//kml:coordinates", "", _KML_NS) or ""

    # A Fläche with no Gelände id has nothing durable to key on, and one with no
    # name cannot be told from its siblings. Either way the ref would not be
    # stable, so the record is dropped rather than given a made-up one.
    if item is None or not name:
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
        id=f"{item.group(1)}-{_slug(name)}",
        name=name,
        role="launch",
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
        group_id=item.group(1),
    )
