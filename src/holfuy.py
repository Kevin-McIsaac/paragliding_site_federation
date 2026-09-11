"""Holfuy stations as a third network - a *catalogue*, not an adapter.

WU answers "what is near this point"; BOM dumps a whole state. Holfuy answers
neither: its official API is password-gated per station with a documented
ceiling of 3 stations, and the map overview that would have carried a bulk
list was retired in 2026-09. What is left is undocumented but public - a
keyless directory at ``/puget/search.php`` giving every station as an id and a
name across 93 countries, and the station monitor page, which server-renders
its own coordinates into the "SHOW ON MAP" link.

So this is not a discovery service and must not become one. It is a
**catalogue build**: walk the directory once, read one number pair off each
station's page, merge the lot into the shared cache under ``network="holfuy"``,
and stop. Coordinates and the station list change rarely, so the build is
manual (``--catalogue``, ~1,670 small GETs, ~30 min at 1 req/s) and every
later run reads the cache with zero Holfuy traffic.

Three properties the rest of the system depends on:

- **Politeness.** Sequential only, ``MIN_REQUEST_INTERVAL_S`` apart, an
  identifying User-Agent, a circuit breaker at 10 consecutive failures, and a
  completeness gate that refuses to publish a partial catalogue.
- **Source-blind matching.** Holfuy stations go into the same ``Cache`` as WU
  and BOM, and ``Cache.nearest`` ranks them purely on distance and liveness.
  But the *pool* gates them: ``network`` never decides who wins, yet it decides
  who is eligible, and Holfuy is opt-in (``pws.OPT_IN_NETWORKS``).
- **Licensing.** Holfuy's directory and names are Holfuy's compilation, so
  Holfuy rows stay out of shipped output until permission is on file. The
  catalogue file is deliberately not tracked in git (``state/`` is published
  by the weekly sync), a Holfuy-inclusive run writes the ``.holfuy-preview``
  output instead of the shipped CSV, and the pool keeps a cached Holfuy
  station from winning a default run. See the README.

How long this lasts: the coordinate link still renders in the HTML, but its
target route is retired. A run that finds no coordinates at all is treated as
a hard failure, not an empty catalogue, because that is exactly what the
field's disappearance looks like.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.pws import Cache, Station, cache_key

#: The network name every Holfuy station carries. Namespaces the cache key
#: (``holfuy:<id>``), so a Holfuy id and a BOM WMO number never collide.
HOLFUY = "holfuy"

#: Undocumented, keyless, called by Holfuy's own ``/js/main.js``. Three forms,
#: all JSON: ``?countries``, ``?country=<CC>``, ``?q=<name>``.
DIRECTORY_URL = "https://holfuy.com/puget/search.php"

#: The station monitor page. ~48 KB, and it server-renders the coordinates.
STATION_URL_TEMPLATE = "https://holfuy.com/en/weather/{station_id}"

#: The "simple mobile view", ~10 KB for the same coordinates. Verified by hand
#: on three stations when the plan was written; if it ever stops carrying the
#: map link, the full page is fetched for that station instead, so a wrong
#: assumption here costs a request rather than a station.
MOBILE_URL_TEMPLATE = "http://m.holfuy.com/{station_id}"

#: Reuse BOM's identifying agent. No browser spoofing: if Holfuy wants to know
#: who is calling, the answer should be true.
USER_AGENT = "paragliding-site-federation/1.0"

#: ~1 request/second, sequential only. A small operator, and the run is manual.
MIN_REQUEST_INTERVAL_S = 1.0

#: The sleeper the module paces with. A module attribute rather than a default
#: argument so tests can replace it for every call site at once - see throttle.
SLEEP = time.sleep

#: Ten failures in a row means the site is refusing us, not that ten stations
#: happen to be broken. Abort rather than grind through 1,573 404s.
MAX_CONSECUTIVE_FAILURES = 10

#: A catalogue that resolved fewer than this share of directory ids is a
#: partial catalogue, which is the failure the app cannot see. Fail the run.
MIN_RESOLVED_SHARE = 0.90

CATALOGUE_PATH = Path("state/holfuy_catalogue.json")

#: The map link, as the live page emits it: ``&amp;`` in the markup, which a
#: lenient parser may or may not have decoded. Both forms parse.
COORDINATES_RE = re.compile(r"la=([-0-9.]+)&(?:amp;)?lo=([-0-9.]+)")

#: ``130m (AMSL)`` on the monitor page. Review data, never used for matching.
ALTITUDE_RE = re.compile(r"(\d+)\s*m\s*\(AMSL\)", re.IGNORECASE)


class HolfuyCatalogueError(RuntimeError):
    """The build could not produce a catalogue worth trusting."""


@dataclass
class Directory:
    """One country's slice of the directory: ids and names, no coordinates.

    ``country`` is the ISO code the directory was asked for on the wire;
    ``country_name`` is the display name from the countries index.
    """

    country: str
    country_name: str
    stations: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Resolved:
    """What one station's page yielded. ``coordinates`` is ``None`` when the
    page carried no map link - a finding, not a (0, 0) station."""

    coordinates: tuple[float, float] | None
    source_page: str
    alt: int | None = None


def parse_countries(payload: object) -> list[tuple[str, str]]:
    """``?countries`` -> ``[(countryCode, countryName)]`` in payload order.

    Tolerant of the wrapping the endpoint may or may not use, and of rows
    missing either half - a nameless country is not addressable, a codeless
    one is not askable.
    """
    countries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for hit in _rows(payload):
        if not isinstance(hit, dict):
            continue
        code = hit.get("countryCode")
        name = hit.get("countryName")
        if not code or not name:
            continue
        code = str(code).strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        countries.append((code, str(name)))
    return countries


def parse_directory(country: str, payload: object) -> Directory:
    """``?country=<CC>`` -> the stations in it: ids and names only."""
    stations: list[tuple[str, str]] = []
    seen: set[str] = set()
    for hit in _rows(payload):
        if not isinstance(hit, dict):
            continue
        station_id = hit.get("id")
        name = hit.get("name")
        if station_id is None or name is None:
            continue
        key = str(station_id).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        stations.append((key, str(name).strip()))
    return Directory(country=country, country_name="", stations=stations)


def parse_coordinates(html: str) -> tuple[float, float] | None:
    """The ``la``/``lo`` pair out of a monitor page's map link.

    Returns ``None`` when the page carries no link at all. That is a *finding*,
    not a zero: a station parsed as 0,0 would sit off the coast of Africa,
    match nothing, and look like coverage.
    """
    match = COORDINATES_RE.search(html or "")
    if match is None:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def parse_altitude(html: str) -> int | None:
    """The page's ``NNNm (AMSL)`` figure, kept for review, not for matching."""
    match = ALTITUDE_RE.search(html or "")
    return int(match.group(1)) if match else None


def station_url(station_id: str) -> str:
    return STATION_URL_TEMPLATE.format(station_id=station_id)


def mobile_url(station_id: str) -> str:
    return MOBILE_URL_TEMPLATE.format(station_id=station_id)


def _rows(payload: object) -> list:
    """The endpoint's array, tolerating an object wrapper around it."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("stations", "items", "results", "data", "countries"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def throttle(clock=time.monotonic, sleeper=None) -> float:
    """Pace requests to ``MIN_REQUEST_INTERVAL_S``, via an injectable clock.

    Same seam as ``pws.throttle``: tests fast-forward, and ``SLEEP`` is a
    module attribute so a test can replace the sleeper the whole module uses -
    ``resolve_station`` and the directory walk both come through here, and a
    fake clock with a real sleeper would hang the suite.

    Returns how long it waited, so the cost is assertable rather than implied.
    """
    state = getattr(throttle, "_last", None)
    now = clock()
    waited = 0.0
    if state is not None and now - state < MIN_REQUEST_INTERVAL_S:
        waited = MIN_REQUEST_INTERVAL_S - (now - state)
        (sleeper or SLEEP)(waited)
    throttle._last = clock()
    return waited


def http_fetcher(url: str) -> str:
    """The real transport: one GET, identifying agent, no retries.

    Retrying lives in :func:`resolve_station`, where the mobile-then-full
    fallback already supplies a second attempt and the circuit breaker is
    watching the run.
    """
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def resolve_station(station_id: str, fetcher, clock=time.monotonic) -> Resolved:
    """One station's coordinates, lighter page first.

    Sequential by construction - there is no concurrency anywhere in this
    module, deliberately. Raises whatever the fetcher raises; the caller
    decides whether that is one station's bad luck or the site refusing us.
    """
    last_url = station_url(station_id)
    for url in (mobile_url(station_id), station_url(station_id)):
        throttle(clock)
        html = fetcher(url)
        last_url = url
        found = parse_coordinates(html)
        if found is not None:
            return Resolved(coordinates=found, source_page=url, alt=parse_altitude(html))
    return Resolved(coordinates=None, source_page=last_url)


@dataclass
class BuildResult:
    """One build's outcome: the catalogue plus the denominator the
    completeness gate was measured against."""

    catalogue: dict[str, dict]
    expected: int


def fetch_catalogue(
    fetcher,
    clock=time.monotonic,
    checkpoint=None,
    on_note=None,
    existing: dict[str, dict] | None = None,
    refresh: bool = False,
) -> BuildResult:
    """Walk the whole directory once and resolve every station's coordinates.

    Returns the catalogue keyed by station id together with the number of ids
    the directory listed - the denominator for the completeness gate, counted
    as the walk goes rather than by a second pass over the directory.

    ``existing`` is what an earlier build already resolved. A station in it is
    carried forward untouched rather than re-fetched, so a build killed halfway
    resumes instead of re-walking 1,573 pages - the same property the WU probe
    loop has. ``refresh=True`` ignores it and re-reads every page, for when
    Holfuy moves a station or fixes a coordinate.

    ``checkpoint(partial)`` is called after each country, so an interrupted
    build keeps its progress on disk. ``on_note(message)`` narrates progress.
    """
    catalogue: dict[str, dict] = dict(existing or {})
    carried = 0
    expected = 0
    consecutive_failures = 0

    throttle._last = None  # a fresh build may fetch immediately

    countries = parse_countries(_fetch_json(DIRECTORY_URL + "?countries", fetcher, clock))
    if not countries:
        raise HolfuyCatalogueError(
            "the Holfuy directory returned no countries - refusing to build an "
            "empty catalogue"
        )
    if on_note:
        on_note(f"{len(countries)} countries in the directory")

    for code, name in countries:
        directory = parse_directory(
            code, _fetch_json(f"{DIRECTORY_URL}?country={code}", fetcher, clock)
        )
        expected += len(directory.stations)
        for station_id, station_name in directory.stations:
            if not refresh and station_id in catalogue:
                carried += 1  # an earlier build already resolved this one
                continue
            try:
                resolved = resolve_station(station_id, fetcher, clock)
            except Exception as error:  # one station's failure is not the run's
                resolved = Resolved(coordinates=None, source_page="")
                if on_note:
                    on_note(f"{station_id}: fetch failed ({error})")
            if resolved.coordinates is None:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise HolfuyCatalogueError(
                        f"aborting after {consecutive_failures} consecutive "
                        f"failures (last: station {station_id}); the site is "
                        f"refusing requests, not failing one station"
                    )
                if on_note:
                    on_note(f"{station_id}: no coordinates on either page")
                continue
            consecutive_failures = 0
            lat, lon = resolved.coordinates
            catalogue[station_id] = {
                "name": station_name,
                "country": code,
                "country_name": name,
                "lat": lat,
                "lon": lon,
                "alt": resolved.alt,
                "url": station_url(station_id),
                "source_page": resolved.source_page,
            }
        if checkpoint is not None:
            checkpoint(catalogue)
        if on_note:
            on_note(f"{code} ({name}): {len(directory.stations)} stations in the "
                    f"directory, {len(catalogue)} resolved so far")
    if carried and on_note:
        on_note(f"{carried} station(s) carried over from the previous catalogue")

    if not catalogue:
        raise HolfuyCatalogueError(
            "resolved no coordinates at all - the monitor pages no longer "
            "carry the map link, which is a hard failure rather than an empty "
            "catalogue"
        )
    return BuildResult(catalogue=catalogue, expected=expected)


def read_catalogue(path: Path) -> dict[str, dict]:
    """The stations already resolved by an earlier build, if any."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    stations = raw.get("stations") if isinstance(raw, dict) else None
    return stations if isinstance(stations, dict) else {}


def catalogue_stations(catalogue: dict[str, dict]) -> list[Station]:
    """Catalogue entries as cache stations.

    No timestamp: the monitor page's "seconds since update" is a reading, not
    a property of the station, and the catalogue is positions only. A Holfuy
    station therefore enters the pool with an unknown age - ``is_alive``
    treats that as alive, so nearest-alive matching weighs a Holfuy station on
    its distance like any other station with no timestamp.

    Elevation is deliberately *not* carried into the cache: it lives in the
    catalogue for review, and the shared cache stays positions-only.
    """
    stations = []
    for station_id, entry in catalogue.items():
        try:
            lat, lon = float(entry["lat"]), float(entry["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        stations.append(
            Station(
                station_id=str(station_id),
                lat=lat,
                lon=lon,
                network=HOLFUY,
                url=entry.get("url") or station_url(str(station_id)),
            )
        )
    return stations


def catalogue_timestamp(catalogue: dict[str, dict]) -> str:
    """The newest ``fetched_utc`` in a catalogue, for the writers.

    Read back from the entries rather than stamped at write time, so a
    catalogue assembled from an earlier build's entries reports when its
    coordinates were actually observed - the year on a coordinate is the
    thing a reviewer needs, not the year of the last save.
    """
    stamps = [
        str(entry["fetched_utc"])
        for entry in catalogue.values()
        if isinstance(entry, dict) and entry.get("fetched_utc")
    ]
    if stamps:
        return max(stamps)
    return _now_iso()


def merge_into_cache(cache: Cache, catalogue: dict[str, dict]) -> int:
    """Merge a catalogue into the shared cache and checkpoint it.

    Namespaced as ``holfuy:<id>`` by :func:`src.pws.cache_key`, so a Holfuy id
    can never shadow a WU or BOM station with the same number.

    Returns the count of stations *new* to the cache, counted here rather than
    read off ``Cache.merge``'s return: that return compares timestamps, and
    Holfuy stations carry none, so a first build would otherwise report zero
    fresh stations.
    """
    stations = catalogue_stations(catalogue)
    fresh = sum(1 for s in stations if cache_key(s) not in cache.stations)
    cache.merge(stations)
    cache.save()
    return fresh


def write_catalogue(
    path: Path,
    catalogue: dict[str, dict],
    fetched_utc: str | None = None,
) -> None:
    """Persist the catalogue with provenance, for audit and for re-runs.

    Atomic replace, same as the cache: a crash mid-write must not leave a
    half-catalogue that the next build would trust.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_utc": fetched_utc or catalogue_timestamp(catalogue),
        "stations": catalogue,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def check_completeness(resolved: int, expected: int) -> None:
    """Refuse a partial catalogue. ``expected`` is the directory's id count."""
    if expected <= 0:
        raise HolfuyCatalogueError("the directory listed no stations to resolve")
    share = resolved / expected
    if share < MIN_RESOLVED_SHARE:
        raise HolfuyCatalogueError(
            f"resolved {resolved} of {expected} directory ids ({share:.0%}), "
            f"below the {MIN_RESOLVED_SHARE:.0%} floor - a silent partial "
            f"catalogue is the failure the app cannot see"
        )


def build(
    cache: Cache,
    fetcher,
    catalogue_path: Path = CATALOGUE_PATH,
    clock=time.monotonic,
    wall_clock=time.time,
    on_note=None,
    refresh: bool = False,
) -> dict[str, dict]:
    """One catalogue build, end to end: fetch, gate, merge, persist.

    Resumable by default: stations an earlier build already resolved are
    carried over instead of re-fetched, and progress is checkpointed to
    ``catalogue_path`` after every country, so a build killed at station 900
    resumes at 900. ``refresh=True`` re-reads every page.

    The order of operations is the safety property: the shared cache is not
    touched until the completeness gate passes, so a partial build can never
    become matchable. The catalogue file is the run's work-in-progress and
    only ever grows, which is what makes the resume safe.
    """
    existing = {} if refresh else read_catalogue(catalogue_path)
    fetched_utc = _stamp(wall_clock())

    def checkpoint(partial: dict[str, dict]) -> None:
        write_catalogue(catalogue_path, partial, fetched_utc=fetched_utc)

    result = fetch_catalogue(
        fetcher=fetcher,
        clock=clock,
        checkpoint=checkpoint,
        on_note=on_note,
        existing=existing,
        refresh=refresh,
    )
    check_completeness(len(result.catalogue), result.expected)
    # Only the newly fetched entries take this build's timestamp; carried-over
    # entries keep the date their coordinates were actually read, which is what
    # a reviewer needs to see.
    for entry in result.catalogue.values():
        entry.setdefault("fetched_utc", fetched_utc)
    merge_into_cache(cache, result.catalogue)
    write_catalogue(catalogue_path, result.catalogue, fetched_utc=fetched_utc)
    if on_note:
        on_note(
            f"{len(result.catalogue)} Holfuy stations merged into {cache.path} "
            f"({len(result.catalogue)}/{result.expected} of the directory)"
        )
    return result.catalogue


def _fetch_json(url: str, fetcher, clock) -> object:
    throttle(clock)
    return json.loads(fetcher(url))


def _stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return _stamp(time.time())
