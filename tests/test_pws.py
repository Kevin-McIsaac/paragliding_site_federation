"""The PWS station match: tiers, cache economics, resumability."""

import json
import time
import urllib.error
from pathlib import Path

from src.pws import (
    DASHBOARD_URL_TEMPLATE,
    Cache,
    Site,
    enrich,
    load_ansg_sites,
    parse_near_response,
    probe,
    write_output,
)
from src.matcher import haversine_m

FIXTURE = Path(__file__).parent / "fixtures" / "pws_near_response.json"


def make_cache(tmp_path, *stations):
    cache = Cache(path=tmp_path / "cache.json")
    cache.merge(list(stations))
    return cache


def fake_transport(payload):
    calls = []

    def call(url, params, api_key):
        calls.append((url, params, api_key))
        return payload

    call.calls = calls
    return call


def test_fixture_matches_the_verified_live_shape():
    """The fixture is the real column-shaped response captured live at the
    Mt Bakewell geocode (the_paragliding_app docs describe an object list -
    the endpoint does not send one)."""
    stations = parse_near_response(json.loads(FIXTURE.read_text()))
    assert [s.station_id for s in stations] == ["IBURGE35", "IYORKYOR1", "IYORK69",
                                                "IYORK348", "IYORK284", "IMALEB3",
                                                "IYORK276", "IBALLA436", "ICOLDH1", "IMALEB2"]
    assert stations[0].lat == -31.85334
    assert stations[2].qc_status == 1


def test_object_shape_is_also_accepted():
    """The shape the app's discovery doc describes, kept as tolerance."""
    payload = {"stations": [{"stationId": "X1", "latitude": 1.0, "longitude": 2.0,
                             "qcStatus": 1, "updateTimeUtc": None}]}
    stations = parse_near_response(payload)
    assert [(s.station_id, s.lat, s.lon, s.update_time_utc) for s in stations] == [("X1", 1.0, 2.0, None)]


def no_probe(*_args):
    raise AssertionError("this run must not spend a probe")


def test_tiers_on_site_nearby_and_beyond(tmp_path):
    station = parse_near_response(json.loads(FIXTURE.read_text()))[0]
    cache = make_cache(tmp_path, station)

    at_150m_lat = station.lat + 150 / 111_320  # ~150 m north
    launch = Site("ansg:1", "Launch", at_150m_lat, station.lon, "300")
    row = enrich([launch], cache, None, no_probe)
    assert (row.matched_on_site, row.matched_nearby, row.unmatched) == (1, 0, 0)

    far = Site("ansg:2", "Far", -31.90, 116.90, "300")  # ~14 km from any fixture station
    row = enrich([far], cache, None, no_probe)
    assert (row.matched_on_site, row.matched_nearby, row.unmatched) == (0, 0, 1)
    assert row.needs_probe == 1  # recordable, not fatal: no key, no probe


def test_nearest_station_wins(tmp_path):
    near, far = parse_near_response(json.loads(FIXTURE.read_text()))[:2]
    cache = make_cache(tmp_path, far, near)
    # ~100 m from IBURGE35, ~1.9 km from IYORKYOR1: both in range, nearest first.
    lat = near.lat + 100 / 111_320
    hit = cache.nearest(lat, near.lon)
    assert hit[0].station_id == "IBURGE35"
    assert hit[1] < 200


def test_cache_hit_spends_no_probe(tmp_path):
    """A site the cache can already answer for must not cost quota."""
    station = parse_near_response(json.loads(FIXTURE.read_text()))[0]
    cache = make_cache(tmp_path, station)
    nearby_site = Site("ansg:3", "Bakewell", station.lat, station.lon, "256")

    transport = fake_transport({})
    stats = enrich([nearby_site], cache, "key", transport)

    assert transport.calls == []
    assert stats.probes == 0


def test_probe_result_is_checkpointed(tmp_path):
    """Kill the run after any probe and the next one resumes, never re-probes."""
    payload = json.loads(FIXTURE.read_text())
    transport = fake_transport(payload)
    cache = Cache(path=tmp_path / "cache.json")
    # ~1.1 km from IYORKYOR1: outside tier 1, inside the probe-coverage radius.
    site = Site("ansg:4", "York", -31.88, 116.77, "256")

    enrich([site], cache, "key", transport, clock=lambda: 0.0)
    assert len(transport.calls) == 1
    reloaded = Cache.load(tmp_path / "cache.json")
    assert "IYORKYOR1" in reloaded.stations  # survived the checkpoint
    assert reloaded.covered(site.lat, site.lon)

    second = enrich([site], Cache.load(tmp_path / "cache.json"), "key", fake_transport(payload))
    assert second.probes == 0


def test_throttle_paces_against_the_shared_key():
    from src import pws

    pws.throttle._last = None  # other tests may have probed with a real clock
    now = [1000.0]
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        now[0] += s

    real_sleep, pws.time.sleep = pws.time.sleep, fake_sleep
    try:
        pws.throttle(lambda: now[0])
        pws.throttle(lambda: now[0] + 1.0)  # only 1 s since the last probe
        assert sleeps == [pws.MIN_PROBE_INTERVAL_S - 1.0]
    finally:
        pws.time.sleep = real_sleep


def test_output_rows_schema_and_lf_endings(tmp_path):
    station = parse_near_response(json.loads(FIXTURE.read_text()))[0]
    cache = make_cache(tmp_path, station)
    sites = [
        Site("ansg:x-1", "Mt Bakewell", station.lat + 0.0005, station.lon, "256"),
        Site("ansg:y-1", "Nowhere", -30.0, 117.0, "100"),
    ]
    out = tmp_path / "site_weather_stations.csv"
    write_output(sites, cache, out, generated_utc="2026-09-05T00:00:00Z")

    data = out.read_bytes()
    assert b"\r" not in data  # the repo's line-ending rule
    lines = data.decode().splitlines()
    header = lines[0].split(",")
    assert "obs_station_id" in header and "obs_station_url" in header

    matched = dict(zip(header, lines[1].split(",")))
    assert matched["obs_station_id"] == "IBURGE35"
    assert matched["obs_station_url"] == DASHBOARD_URL_TEMPLATE.format(station_id="IBURGE35")
    assert matched["obs_station_tier"] == "on-site"
    assert matched["obs_source"] == "wu-pws"
    assert matched["obs_station_last_obs_epoch"] == "1788784768"  # the API's epoch, not ISO

    unmatched = dict(zip(header, lines[2].split(",")))
    assert unmatched["obs_station_id"] == ""  # present, empty: a finding too
    assert unmatched["obs_station_tier"] == ""


def test_load_anssg_sites_reads_the_app_catalog(tmp_path):
    catalog = tmp_path / "sites.csv"
    catalog.write_text(
        "id,ref,name,longitude,latitude,altitude,country\n"
        '1,ansg:a,"Site, With Comma",116.7,-31.8,256,au\n'
        "2,pge:1,PGE Site,116.7,-31.8,256,au\n"
        "3,ansg:b,No Coords,,,256,au\n",
        encoding="utf-8",
    )
    sites = load_ansg_sites(catalog)
    assert [s.ref for s in sites] == ["ansg:a"]  # only ANSG rows, only with coords
    assert sites[0].name == "Site, With Comma"


def test_pge_rows_are_scoped_to_australia(tmp_path):
    """'pge-au' means PGE worldwide filtered to AU - a New Zealand PGE launch
    must not ride in on a shared ref prefix."""
    from src.pws import load_sites

    catalog = tmp_path / "sites.csv"
    catalog.write_text(
        "id,ref,name,longitude,latitude,altitude,country\n"
        "1,pge:1,AU PGE,116.7,-31.8,256,au\n"
        "2,pge:2,NZ PGE,172.8,-36.8,120,nz\n"
        "3,ansg:a,ANSG AU,116.7,-31.9,256,au\n",
        encoding="utf-8",
    )
    sites = load_sites(catalog, prefixes=("ansg:", "pge:"), countries=frozenset({"au"}))
    assert [s.ref for s in sites] == ["pge:1", "ansg:a"]  # catalog order, NZ excluded


def test_probe_uses_the_documented_endpoint():
    from src.pws import NEAR_URL

    transport = fake_transport({"stations": []})
    probe(-31.853, 116.765, "key", transport)
    url, params, api_key = transport.calls[0]
    assert url == NEAR_URL
    assert params["geocode"] == "-31.853,116.765"  # lat first, WGS84
    assert params["product"] == "pws"
    assert api_key == "key"


def test_empty_answer_is_recorded_not_reprobed(tmp_path):
    """The endpoint 404s a stationless geocode. That is an answer: the probe
    is spent once, the empty point is checkpointed, and a re-run spends
    nothing - it does not grind on the same site forever."""
    from src.pws import EMPTY_PROBE_RADIUS_M

    def forty(url, params, api_key):
        # What http_transport hands enrich after translating a 404.
        return {"location": {"stationId": []}}

    fixture = json.loads(FIXTURE.read_text())

    def by_geocode(url, params, api_key):
        if params["geocode"].startswith("-25."):
            return forty(url, params, api_key)
        return fixture

    def stations_response(url, params, api_key):
        return fixture

    remote = Site("ansg:9", "Remote", -25.0, 130.0, "300")  # no stations anywhere near
    covered = Site("ansg:5", "York", -31.88, 116.77, "256")

    cache = Cache(path=tmp_path / "cache.json")
    stats = enrich([remote, covered], cache, "key", by_geocode, clock=lambda: 0.0)
    assert stats.probes == 2 and stats.needs_probe == 0
    assert stats.matched_nearby == 1  # York matched from its own probe

    # The empty probe is durable and covers the neighbourhood.
    reloaded = Cache.load(tmp_path / "cache.json")
    assert reloaded.empty_probes == [(-25.0, 130.0)]
    again = enrich([remote], reloaded, "key", forty, clock=lambda: 0.0)
    assert again.probes == 0

    # A stationless point only answers within its conservative radius.
    just_outside = Site("ansg:6", "Edge", -25.0, 130.0 + EMPTY_PROBE_RADIUS_M / 85_000 + 0.001, "300")
    assert not reloaded.covered(just_outside.lat, just_outside.lon)


def test_transport_404_becomes_an_empty_answer():
    from scripts.wu_pws_stations import http_transport

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    real_urlopen = urllib.request.urlopen

    def raise_404(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    urllib.request.urlopen = raise_404
    try:
        assert http_transport("https://x/v3/location/near", {}, "key") == {"location": {"stationId": []}}
    finally:
        urllib.request.urlopen = real_urlopen


def test_transport_backs_off_on_429_then_gives_up():
    from scripts.wu_pws_stations import http_transport

    calls, sleeps = [], []

    def rate_limited(url, timeout):
        calls.append(url)
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    real_urlopen, real_sleep = urllib.request.urlopen, time.sleep
    urllib.request.urlopen, time.sleep = rate_limited, sleeps.append
    try:
        try:
            http_transport("https://x/v3/location/near", {}, "key")
            raised = False
        except urllib.error.HTTPError:
            raised = True  # the original 429, after backing off twice
        assert raised and len(calls) == 3 and sleeps == [60, 120]
    finally:
        urllib.request.urlopen, time.sleep = real_urlopen, real_sleep
