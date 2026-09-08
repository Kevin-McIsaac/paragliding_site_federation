"""Match launches to nearby Weather Underground PWS stations.

The site catalog answers "where can I launch". This answers "what is the wind
doing there right now", by giving each launch the id of its nearest WU personal
weather station (PWS) - a thing the site itself does not carry.

The economics that shape the whole module: the only WU call that costs quota is
discovery (``v3/location/near``, 1500/day and 30/minute per key, shared with
the app's live map layer). That one response already carries every station's
coordinates, QC status and last-update time - so the 200 m matching, the tier
assignment and the liveness flags are all *free* offline work against a
persistent station cache. The probe phase therefore spends a call only where
the cache cannot answer, checkpoints the cache after every probe so an
interrupted run resumes instead of re-probing, and re-runs cost ~zero.

Match rule (decided 2026-09): nearest station first; ``on-site`` tier within
ON_SITE_RADIUS_M, ``nearby`` tier within NEARBY_RADIUS_M, nothing beyond. A
cache hit inside NEARBY_RADIUS_M is accepted without probing - it is the
nearest station among the ones discovered, which is the rule that was agreed,
not a proof of global nearestness.
"""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.matcher import haversine_m

#: Tier 1 - a station this close is treated as the launch's own weather.
ON_SITE_RADIUS_M = 200.0

#: Tier 2 - usable context, but flagged, because a station 2 km away and
#: downhill does not describe the wind on the hill.
NEARBY_RADIUS_M = 2000.0

NEAR_URL = "https://api.weather.com/v3/location/near"
DASHBOARD_URL_TEMPLATE = "https://www.wunderground.com/dashboard/pws/{station_id}"
OBS_SOURCE = "wu-pws"

#: A geocode whose discovery probe found no stations. An empty answer covers
#: nearby points too (see Cache.empty_probes).
EMPTY_PROBE_RADIUS_M = 2000.0

#: ~17 calls/minute against a 30/minute limit the app's map layer shares.
MIN_PROBE_INTERVAL_S = 3.5

CACHE_PATH = Path("state/pws_station_cache.json")
OUTPUT_PATH = Path("app/site_weather_stations.csv")
SITES_PATH = Path("app/sites.csv")

OUTPUT_FIELDS = [
    "site_ref",
    "site_name",
    "site_lat",
    "site_lon",
    "site_alt",
    "obs_source",
    "obs_station_id",
    "obs_station_url",
    "obs_station_distance_m",
    "obs_station_tier",
    "obs_station_qc",
    "obs_station_last_obs_epoch",  # the API's updateTimeUtc: seconds, not ISO
    "generated_utc",
]


@dataclass
class Station:
    station_id: str
    lat: float
    lon: float
    qc_status: int | None = None
    update_time_utc: str | None = None


@dataclass
class Cache:
    """Every station a discovery probe has ever returned, keyed by id.

    Written back after *each* probe: the file is the run's checkpoint, so
    killing the batch midway costs nothing but the probe in flight.
    """

    path: Path
    stations: dict[str, Station] = field(default_factory=dict)
    #: Geocodes whose probe came back with no stations at all. The endpoint
    #: answers a stationless area with HTTP 404, which is an *answer*, not an
    #: error - recording the point is what keeps a re-run from re-probing it
    #: forever. Coverage is conservative (EMPTY_PROBE_RADIUS_M): if the
    #: endpoint's search radius turns out smaller than our tier-2 radius, a
    #: later run simply probes again.
    empty_probes: list[tuple[float, float]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Cache":
        cache = cls(path=path)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            cache.stations = {sid: Station(**s) for sid, s in raw.get("stations", {}).items()}
            cache.empty_probes = [tuple(p) for p in raw.get("empty_probes", [])]
        return cache

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stations": {
                sid: {
                    "station_id": s.station_id,
                    "lat": s.lat,
                    "lon": s.lon,
                    "qc_status": s.qc_status,
                    "update_time_utc": s.update_time_utc,
                }
                for sid, s in self.stations.items()
            },
            "empty_probes": [[lat, lon] for lat, lon in self.empty_probes],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def merge(self, stations: list[Station]) -> int:
        """Add stations not already cached; freshness always wins."""
        fresh = 0
        for s in stations:
            old = self.stations.get(s.station_id)
            if old is None or s.update_time_utc != old.update_time_utc:
                fresh += 1
            self.stations[s.station_id] = s
        return fresh

    def nearest(self, lat: float, lon: float) -> tuple[Station, float] | None:
        best: tuple[Station, float] | None = None
        for s in self.stations.values():
            d = haversine_m(lat, lon, s.lat, s.lon)
            if best is None or d < best[1]:
                best = (s, d)
        return best

    def covered(self, lat: float, lon: float) -> bool:
        """True when the cache can already answer for this point: a station
        within the tier-2 radius, or a probe that came back empty nearby."""
        hit = self.nearest(lat, lon)
        if hit is not None and hit[1] <= NEARBY_RADIUS_M:
            return True
        return any(
            haversine_m(lat, lon, p[0], p[1]) <= EMPTY_PROBE_RADIUS_M
            for p in self.empty_probes
        )


@dataclass
class Site:
    ref: str
    name: str
    lat: float
    lon: float
    alt: str


def load_ansg_sites(sites_path: Path = SITES_PATH) -> list[Site]:
    sites: list[Site] = []
    with open(sites_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref = row.get("ref", "")
            if not ref.startswith("ansg:"):
                continue
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
            except (TypeError, ValueError):
                continue  # no coordinates, no station match possible
            sites.append(
                Site(
                    ref=ref,
                    name=row.get("name", ""),
                    lat=lat,
                    lon=lon,
                    alt=row.get("altitude", ""),
                )
            )
    return sites


def parse_near_response(payload: dict) -> list[Station]:
    """Pull the stations out of a v3/location/near response.

    The live endpoint returns *column-oriented* data - ``location`` holding
    parallel arrays (``stationId[]``, ``latitude[]``, ``longitude[]``,
    ``qcStatus[]`` (1 = QC passed, -1 = none), ``updateTimeUtc[]``) - which is
    not the list-of-objects shape the app's discovery doc describes. Both
    shapes are accepted here; the fixture is the real verified column shape.
    ``distanceKm`` is not kept - the haversine against our own launch
    coordinates is what the tiers use.
    """
    location = payload.get("location")
    if isinstance(location, dict) and isinstance(location.get("stationId"), list):
        # Column shape: zip the parallel arrays defensively over the shortest.
        ids = location["stationId"]
        lats = location.get("latitude") or []
        lons = location.get("longitude") or []
        qc = location.get("qcStatus") or []
        updated = location.get("updateTimeUtc") or []
        stations = []
        for i, station_id in enumerate(ids):
            if i >= len(lats) or i >= len(lons) or lats[i] is None or lons[i] is None:
                continue
            stations.append(
                Station(
                    station_id=str(station_id),
                    lat=float(lats[i]),
                    lon=float(lons[i]),
                    qc_status=qc[i] if i < len(qc) else None,
                    update_time_utc=updated[i] if i < len(updated) else None,
                )
            )
        return stations
    # Object shape: a list of station objects (documented, kept for tolerance).
    stations = []
    for hit in location if isinstance(location, list) else payload.get("stations") or []:
        station_id = hit.get("stationId")
        lat, lon = hit.get("latitude"), hit.get("longitude")
        if not station_id or lat is None or lon is None:
            continue
        stations.append(
            Station(
                station_id=str(station_id),
                lat=float(lat),
                lon=float(lon),
                qc_status=hit.get("qcStatus"),
                update_time_utc=hit.get("updateTimeUtc"),
            )
        )
    return stations


def probe(
    lat: float,
    lon: float,
    api_key: str,
    transport,
) -> list[Station]:
    """One discovery call, via an injectable transport (tests pass a fake)."""
    payload = transport(NEAR_URL, {"geocode": f"{lat},{lon}", "product": "pws", "format": "json"}, api_key)
    return parse_near_response(payload)


def throttle(clock) -> None:
    """Sleep to the shared-key rate budget. ``clock`` returns the current
    monotonic time, so tests can fast-forward without waiting."""
    state = getattr(throttle, "_last", None)
    now = clock()
    if state is not None:
        waited = now - state
        if waited < MIN_PROBE_INTERVAL_S:
            time.sleep(MIN_PROBE_INTERVAL_S - waited)
    throttle._last = clock()


@dataclass
class RunStats:
    probes: int = 0
    sites: int = 0
    needs_probe: int = 0
    matched_on_site: int = 0
    matched_nearby: int = 0
    unmatched: int = 0


def enrich(
    sites: list[Site],
    cache: Cache,
    api_key: str | None,
    transport,
    clock=time.monotonic,
) -> RunStats:
    """Probe where the cache is silent and a key is available, then match
    every site offline. Sites left unprobed are counted in ``needs_probe``
    and simply match against whatever the cache holds - probing and
    matching stay separable, so an offline run is still useful."""
    stats = RunStats(sites=len(sites))
    throttle._last = None  # a fresh run may probe immediately
    for site in sites:
        if cache.covered(site.lat, site.lon):
            continue
        if not api_key:
            stats.needs_probe += 1
            continue
        throttle(clock)
        found = probe(site.lat, site.lon, api_key, transport)
        if not found:
            cache.empty_probes.append((site.lat, site.lon))
        cache.merge(found)
        cache.save()  # checkpoint: the next run resumes here
        stats.probes += 1
    for site in sites:
        hit = cache.nearest(site.lat, site.lon)
        if hit is None or hit[1] > NEARBY_RADIUS_M:
            stats.unmatched += 1
        elif hit[1] <= ON_SITE_RADIUS_M:
            stats.matched_on_site += 1
        else:
            stats.matched_nearby += 1
    return stats


def match_row(site: Site, cache: Cache, generated_utc: str) -> dict[str, str]:
    row = {field: "" for field in OUTPUT_FIELDS}
    row.update(
        site_ref=site.ref,
        site_name=site.name,
        site_lat=f"{site.lat:.6f}",
        site_lon=f"{site.lon:.6f}",
        site_alt=site.alt,
        obs_source=OBS_SOURCE,
        generated_utc=generated_utc,
    )
    hit = cache.nearest(site.lat, site.lon)
    if hit is not None and hit[1] <= NEARBY_RADIUS_M:
        station, distance = hit
        row.update(
            obs_station_id=station.station_id,
            obs_station_url=DASHBOARD_URL_TEMPLATE.format(station_id=station.station_id),
            obs_station_distance_m=f"{distance:.0f}",
            obs_station_tier="on-site" if distance <= ON_SITE_RADIUS_M else "nearby",
            obs_station_qc="" if station.qc_status is None else str(station.qc_status),
            obs_station_last_obs_epoch=station.update_time_utc if station.update_time_utc is not None else "",
        )
    return row


def write_output(
    sites: list[Site],
    cache: Cache,
    output_path: Path = OUTPUT_PATH,
    generated_utc: str = "",
) -> None:
    """Every ANSG site gets a row, matched or not - an absent station is a
    finding too, and the empty tier says so without a join back to sites.csv."""
    import io

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(OUTPUT_FIELDS)
        for site in sites:
            buffer = io.StringIO()
            csv.writer(buffer, lineterminator="").writerow(
                [match_row(site, cache, generated_utc)[k] for k in OUTPUT_FIELDS]
            )
            f.write(buffer.getvalue() + "\n")


def run(
    transport,
    api_key: str | None = None,
    cache_path: Path = CACHE_PATH,
    output_path: Path = OUTPUT_PATH,
    sites_path: Path = SITES_PATH,
    cache_only: bool = False,
    clock=time.monotonic,
    generated_utc: str = "",
) -> RunStats:
    sites = load_ansg_sites(sites_path)
    cache = Cache.load(cache_path)
    if not cache_only and not api_key:
        needing = sum(1 for s in sites if not cache.covered(s.lat, s.lon))
        if needing:
            raise SystemExit(
                f"WUNDERGROUND_API_KEY is not set and the cache cannot answer "
                f"for {needing} site(s) - set the key, or use --cache-only to "
                f"write the partial match"
            )
    if cache_only:
        api_key = None
    stats = enrich(sites, cache, api_key, transport, clock)
    write_output(sites, cache, output_path, generated_utc)
    return stats
