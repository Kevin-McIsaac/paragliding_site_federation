"""The Holfuy catalogue: parsing, politeness, gating, and the licensing gate.

No network anywhere in this file: every fetch is a fake, and the clock is a
list the test advances by hand.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from src import holfuy
from src.holfuy import (
    HOLFUY,
    MIN_REQUEST_INTERVAL_S,
    HolfuyCatalogueError,
    HolfuyUnreachable,
    build,
    catalogue_stations,
    check_completeness,
    fetch_catalogue,
    http_fetcher,
    is_connection_refusal,
    merge_into_cache,
    parse_altitude,
    parse_coordinates,
    parse_countries,
    parse_directory,
    preflight,
    read_catalogue,
    resolve_station,
    throttle,
)
from src.pws import Cache, Site, Station, cache_key, match_row

FIXTURES = Path(__file__).parent / "fixtures"

COUNTRIES = FIXTURES / "holfuy_countries.json"
DIRECTORY_NO = FIXTURES / "holfuy_directory_no.json"
STATION_142 = FIXTURES / "holfuy_station_142.html"
STATION_351 = FIXTURES / "holfuy_station_351.html"
STATION_NO_MAP = FIXTURES / "holfuy_station_no_map.html"


def _fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FakeFetcher:
    """A fetcher that serves fixtures by URL and records the call order."""

    def __init__(self, routes: dict, default: str | None = None):
        self.routes = routes
        self.default = default
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float | None = None) -> str:
        self.calls.append(url)
        if url in self.routes:
            return self.routes[url]
        if self.default is not None:
            return self.default
        raise AssertionError(f"unexpected fetch: {url}")


class FakeClock:
    """Monotonic seconds that only move when the code sleeps."""

    def __init__(self, start: float = 0.0):
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def fake_sleep(monkeypatch):
    """The throttle stores its last-call time on the function itself, and
    sleeps through a module attribute. Replace both so no test can really
    sleep: a fake clock with a real sleeper hangs the suite."""
    clock = FakeClock()
    monkeypatch.setattr(holfuy, "SLEEP", clock.sleep)
    holfuy.throttle._last = None
    yield clock
    holfuy.throttle._last = None


# --- parsing -----------------------------------------------------------------


def test_countries_fixture_parses_and_drops_unaddressable_rows():
    """A codeless or nameless row cannot be walked, so it is not a country."""
    countries = parse_countries(json.loads(COUNTRIES.read_text()))
    assert countries == [
        ("NO", "Norway"),
        ("CH", "Switzerland"),
        ("ES", "Spain"),
        ("US", "United States"),
    ]


def test_countries_tolerates_an_object_wrapper():
    payload = {"countries": [{"countryCode": "no", "countryName": "Norway"}]}
    assert parse_countries(payload) == [("NO", "Norway")]  # code normalised


def test_directory_keeps_ids_and_names_and_drops_duplicates():
    directory = parse_directory("NO", json.loads(DIRECTORY_NO.read_text()))
    assert directory.country == "NO"
    assert [s[0] for s in directory.stations] == ["142", "351", "1222"]
    assert directory.stations[0] == ("142", "THPK Ersfjord")


@pytest.mark.parametrize(
    "fixture, expected",
    [
        (STATION_142, (69.70017, 18.63842)),  # the live page emits &amp;
        (STATION_351, (43.099772, -2.533773)),  # a decoded & must parse too
    ],
)
def test_coordinates_parse_from_both_ampersand_forms(fixture, expected):
    lat, lon = parse_coordinates(_fixture(fixture))
    assert (lat, lon) == expected


def test_altitude_is_read_for_review_only():
    assert parse_altitude(_fixture(STATION_142)) == 130
    assert parse_altitude(_fixture(STATION_351)) == 640
    assert parse_altitude(_fixture(STATION_NO_MAP)) is None


def test_altitude_parses_the_live_markup_not_the_plan_prose():
    """The plan quotes the page as ``130m (AMSL)``, which is prose-normalised.
    The live markup is ``<b>130m</b> (AMSL)`` - the figure is emphasised, so a
    closing tag sits between the unit and the qualifier. A regex written from
    the plan's prose matched no page at all and silently reported 0% altitude
    coverage, which is the failure this pins."""
    live = '<p>Station owner: Norway&comma; Troms&oslash;, <b>130m</b> (AMSL)  <a href="/en/map/la=69.7&lo=18.6">m</a></p>'
    assert parse_altitude(live) == 130
    assert parse_altitude("elevation 1,240m</b> (AMSL)") == 1240
    # The prose form still parses, and a number with no AMSL qualifier does not.
    assert parse_altitude("130m (AMSL)") == 130
    assert parse_altitude("wind 12 m/s, gust 18 m/s") is None
    assert parse_altitude("<b>130m</b> above sea level") is None


def test_a_page_with_no_map_link_is_a_finding_not_a_zero():
    """The negative test the plan calls for: a missing link must not parse as
    0,0, which would sit off the coast of Africa and look like coverage."""
    assert parse_coordinates(_fixture(STATION_NO_MAP)) is None


def test_impossible_coordinates_are_rejected():
    assert parse_coordinates('href="la=99.5&lo=18.6"') is None
    assert parse_coordinates('href="la=69.7&amp;lo=200.0"') is None


# --- fetching ----------------------------------------------------------------


def test_a_station_costs_exactly_one_request(fake_sleep):
    """No mobile fast path: the mobile view carries no map link on any station
    measured, so a first attempt there is a doomed request against a small
    operator. One station, one fetch, to the monitor page."""
    fetcher = FakeFetcher({holfuy.station_url("142"): _fixture(STATION_142)})
    resolved = resolve_station("142", fetcher, fake_sleep)

    assert fetcher.calls == [holfuy.station_url("142")]
    assert resolved.coordinates == (69.70017, 18.63842)
    assert resolved.source_page == holfuy.station_url("142")
    assert resolved.alt == 130


def test_the_mobile_host_is_never_contacted(tmp_path, fake_sleep):
    """The finding behind dropping the fast path, pinned so it cannot creep
    back: the module has no mobile URL to call at all."""
    assert not hasattr(holfuy, "mobile_url")
    assert not hasattr(holfuy, "MOBILE_URL_TEMPLATE")

    fetcher = _build_fetcher()
    build(cache=Cache(path=tmp_path / "cache.json"), fetcher=fetcher,
          catalogue_path=tmp_path / "cat.json", clock=fake_sleep,
          wall_clock=lambda: 1_789_000_000.0)
    assert not any("m.holfuy.com" in url for url in fetcher.calls)


def test_throttle_paces_against_the_small_operator(fake_sleep):
    throttle(fake_sleep, fake_sleep.sleep)  # first call is free
    throttle(fake_sleep, fake_sleep.sleep)  # only 0 s since the last one
    assert fake_sleep.sleeps == [MIN_REQUEST_INTERVAL_S]


def test_circuit_breaker_trips_after_ten_consecutive_failures(fake_sleep):
    countries = json.dumps([{"countryCode": "NO", "countryName": "Norway"}])
    many = json.dumps([{"id": i, "name": f"S{i}"} for i in range(40)])
    fetcher = FakeFetcher(
        {holfuy.DIRECTORY_URL + "?countries": countries,
         holfuy.DIRECTORY_URL + "?country=NO": many},
        default=_fixture(STATION_NO_MAP),
    )
    with pytest.raises(HolfuyCatalogueError, match="consecutive failures"):
        fetch_catalogue(fetcher=fetcher, clock=fake_sleep)


# --- the blocked network, which is not a data problem ------------------------


def test_every_url_the_build_fetches_is_https():
    """The host refuses by IP, and a plaintext request is both the likelier to
    be refused and the one that cannot negotiate through a TLS-fronted block.
    Nothing in this module speaks http."""
    assert holfuy.station_url("142").startswith("https://")
    assert holfuy.DIRECTORY_URL.startswith("https://")
    assert not holfuy.station_url("142").startswith("http://")
    assert not holfuy.DIRECTORY_URL.startswith("http://")


def test_refusal_detection_covers_the_transport_errors_we_actually_hit():
    """The failure this was written for: holfuy.com answered, then started
    refusing connections outright on 162.55.38.193."""
    assert is_connection_refusal(
        urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    )
    assert is_connection_refusal(
        urllib.error.URLError(TimeoutError("timed out"))
    )
    assert is_connection_refusal(ConnectionResetError("Connection reset by peer"))
    # An HTTP status means something answered; whether it is a refusal is
    # UNAVAILABLE_CODES' decision, not this function's.
    assert not is_connection_refusal(
        urllib.error.HTTPError("https://holfuy.com/", 403, "Forbidden", {}, None)
    )
    assert not is_connection_refusal(ValueError("not a network error"))


def test_http_fetcher_calls_a_refusal_unreachable_and_names_the_fix(monkeypatch):
    def refuse(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(HolfuyUnreachable) as caught:
        http_fetcher("https://holfuy.com/puget/search.php?countries")

    message = str(caught.value)
    assert "holfuy.com" in message  # which host refused
    assert "refusing requests" in message  # what happened
    assert "datacenter" in message  # the likely reason
    assert "different network" in message  # and what to do about it
    # A bare catalogue error would send the operator looking for a data bug.
    assert isinstance(caught.value, HolfuyCatalogueError)


def test_an_access_blocked_page_is_unreachable_not_a_missing_station(monkeypatch):
    """403 is Holfuy's "Access blocked" page served to datacenter ranges; 429 is
    "too many requests". Neither is a station that has gone away."""

    def blocked(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://holfuy.com/en/weather/142", 403, "Forbidden", {}, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", blocked)

    with pytest.raises(HolfuyUnreachable, match="HTTP 403"):
        http_fetcher("https://holfuy.com/en/weather/142")


def test_a_plain_404_stays_a_404_rather_than_becoming_a_block(monkeypatch):
    """The distinction the typed error exists to keep: a vanished station must
    not abort a whole build that is otherwise working."""

    def missing(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://holfuy.com/en/weather/1", 404, "Not Found", {}, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", missing)

    with pytest.raises(urllib.error.HTTPError) as caught:
        http_fetcher("https://holfuy.com/en/weather/1")
    assert not isinstance(caught.value, HolfuyUnreachable)


def test_preflight_returns_the_countries_the_walk_will_need(fake_sleep):
    """It must hand back its answer, because the walk needs the same list and a
    preflight that made the walk fetch it again would be a wasted request."""
    fetcher = _build_fetcher()
    countries = preflight(fetcher=fetcher, clock=fake_sleep)
    assert [code for code, _ in countries] == ["NO", "ES"]


def test_a_blocked_source_raises_unreachable_not_a_missing_map_link(fake_sleep):
    """The regression that motivated the typed error. A page that *answers*
    without a map link is a finding about the field; a page that never answers
    is a fact about our network, and the run must say so instead of reporting
    that Holfuy's pages lost their coordinates."""

    class Unreachable(FakeFetcher):
        def __call__(self, url, timeout=None):
            self.calls.append(url)
            raise HolfuyUnreachable("holfuy.com is refusing requests")

    fetcher = Unreachable({holfuy.DIRECTORY_URL + "?countries":
                           json.dumps([{"countryCode": "NO", "countryName": "Norway"}])})

    with pytest.raises(HolfuyUnreachable):
        fetch_catalogue(fetcher=fetcher, clock=fake_sleep)


def test_the_catalogue_does_not_report_a_fetch_failure_as_a_station_finding(fake_sleep):
    """The other half: a station whose page raises an ordinary network error is
    still one station's bad luck, counted and moved past."""

    class Flaky(FakeFetcher):
        def __init__(self):
            super().__init__({
                holfuy.DIRECTORY_URL + "?countries":
                    json.dumps([{"countryCode": "NO", "countryName": "Norway"}]),
                holfuy.DIRECTORY_URL + "?country=NO":
                    json.dumps([{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]),
                holfuy.station_url("2"): _fixture(STATION_142),
            }, default=_fixture(STATION_NO_MAP))

        def __call__(self, url, timeout=None):
            if url == holfuy.station_url("1"):
                self.calls.append(url)
                raise urllib.error.URLError(OSError("connection reset"))
            return super().__call__(url)

    notes = []
    result = fetch_catalogue(fetcher=Flaky(), clock=fake_sleep, on_note=notes.append)

    assert set(result.catalogue) == {"2"}  # the good station still resolved
    assert any("fetch failed" in note for note in notes)


def test_build_preflights_and_fails_fast_without_walking_the_directory(
    tmp_path, fake_sleep
):
    """A blocked run must cost one request, not 93 country index fetches. The
    plan's whole complaint about the untyped path was that it spent a minute and
    a half proving a fact one request establishes."""

    class Blocked(FakeFetcher):
        """Refuses by IP, which is exactly what http_fetcher now turns into a
        typed HolfuyUnreachable. Raising the bare URLError would only exercise
        this test's own stub; this is the real transport's contract."""

        def __call__(self, url, timeout=None):
            self.calls.append(url)
            raise holfuy.unreachable_for(url, "Connection refused")

    fetcher = Blocked({})
    with pytest.raises(HolfuyUnreachable):
        build(cache=Cache(path=tmp_path / "cache.json"), fetcher=fetcher,
              catalogue_path=tmp_path / "cat.json", clock=fake_sleep)

    assert fetcher.calls == [holfuy.DIRECTORY_URL + "?countries"]  # stopped at the first
    assert not (tmp_path / "cat.json").exists()  # nothing partial was written


def test_build_reuses_the_preflight_answer_instead_of_fetching_it_twice(
    tmp_path, fake_sleep
):
    """One directory read, not two: the preflight's countries are passed into
    the walk. A duplicate here is invisible in the output and only shows up as
    an extra request against a source we are trying not to burden."""

    fetcher = _build_fetcher()
    build(cache=Cache(path=tmp_path / "cache.json"), fetcher=fetcher,
          catalogue_path=tmp_path / "cat.json", clock=fake_sleep,
          wall_clock=lambda: 1_789_000_000.0)

    countries_url = holfuy.DIRECTORY_URL + "?countries"
    assert fetcher.calls.count(countries_url) == 1


# --- the catalogue and the cache --------------------------------------------


def test_completeness_gate_refuses_a_partial_catalogue():
    check_completeness(950, 1000)  # 95% is fine
    with pytest.raises(HolfuyCatalogueError, match="below the 90% floor"):
        check_completeness(899, 1000)
    with pytest.raises(HolfuyCatalogueError, match="no stations"):
        check_completeness(0, 0)


def test_holfuy_id_cannot_collide_with_a_wu_or_bom_id(tmp_path):
    cache = Cache(path=tmp_path / "cache.json")
    cache.merge([Station("142", 10.0, 20.0, network="wu-pws")])
    cache.save()

    fresh = merge_into_cache(cache, {"142": {"lat": 69.7, "lon": 18.6}})

    assert fresh == 1  # counted here: Holfuy entries carry no timestamp
    assert len(cache.stations) == 2
    assert cache_key(Station("142", 0, 0, network=HOLFUY)) in cache.stations
    reloaded = Cache.load(tmp_path / "cache.json")
    assert reloaded.stations["holfuy:142"].lat == 69.7


def test_a_holfuy_station_with_no_timestamp_counts_as_alive(tmp_path):
    """Positions have no observation time, and liveness is a signal not a gate:
    a Holfuy station must not be treated as dead and lose to a farther live one
    for the wrong reason."""
    cache = Cache(path=tmp_path / "cache.json")
    merge_into_cache(cache, {"142": {"lat": -31.85, "lon": 116.76}})
    hit = cache.nearest(-31.85, 116.76, now=1_800_000_000.0)
    assert hit[0].network == HOLFUY


def test_catalogue_survives_a_round_trip(tmp_path):
    path = tmp_path / "holfuy_catalogue.json"
    catalogue = {
        "142": {"name": "THPK Ersfjord", "country": "NO", "country_name": "Norway",
                "lat": 69.70017, "lon": 18.63842, "alt": 130,
                "url": holfuy.station_url("142"),
                "source_page": holfuy.station_url("142"),
                "fetched_utc": "2026-09-11T00:00:00Z"},
    }
    holfuy.write_catalogue(path, catalogue)
    assert read_catalogue(path) == catalogue
    assert read_catalogue(tmp_path / "absent.json") == {}
    (tmp_path / "garbage.json").write_text("{not json")
    assert read_catalogue(tmp_path / "garbage.json") == {}


def test_catalogue_entries_become_holfuy_stations():
    stations = catalogue_stations({
        "142": {"lat": 69.70017, "lon": 18.63842, "alt": 130,
                "url": holfuy.station_url("142")},
        "broken": {"lat": "north"},
    })
    assert [s.station_id for s in stations] == ["142"]
    assert stations[0].network == HOLFUY
    assert stations[0].elevation is None  # altitude stays out of the cache


# --- the build, end to end ---------------------------------------------------


def _build_fetcher():
    """A whole miniature directory: two countries, three stations."""
    countries = json.dumps([
        {"countryCode": "NO", "countryName": "Norway", "count": 2},
        {"countryCode": "ES", "countryName": "Spain", "count": 1},
    ])
    return FakeFetcher({
        holfuy.DIRECTORY_URL + "?countries": countries,
        holfuy.DIRECTORY_URL + "?country=NO": json.dumps(
            [{"id": 142, "name": "THPK Ersfjord"}, {"id": 351, "name": "Elorrio-Udalaitz"}]
        ),
        holfuy.DIRECTORY_URL + "?country=ES": json.dumps(
            [{"id": 1222, "name": "Pointy Knob"}]
        ),
        holfuy.station_url("142"): _fixture(STATION_142),
        holfuy.station_url("351"): _fixture(STATION_351),
        holfuy.station_url("1222"): _fixture(STATION_142),
    })


def test_build_merges_into_the_cache_and_writes_the_catalogue(tmp_path, fake_sleep):
    cache = Cache(path=tmp_path / "cache.json")
    catalogue_path = tmp_path / "holfuy_catalogue.json"
    notes = []

    catalogue = build(
        cache=cache,
        fetcher=_build_fetcher(),
        catalogue_path=catalogue_path,
        clock=fake_sleep,
        wall_clock=lambda: 1_789_000_000.0,
        on_note=notes.append,
    )

    assert sorted(catalogue) == ["1222", "142", "351"]
    assert catalogue["142"]["name"] == "THPK Ersfjord"
    assert catalogue["142"]["country"] == "NO"
    assert catalogue["142"]["country_name"] == "Norway"
    assert catalogue["142"]["alt"] == 130
    assert catalogue["142"]["fetched_utc"] == "2026-09-10T00:26:40Z"

    cached = Cache.load(tmp_path / "cache.json")
    assert cached.stations["holfuy:142"].lon == 18.63842

    written = json.loads(catalogue_path.read_text())
    assert written["generated_utc"] == "2026-09-10T00:26:40Z"
    assert set(written["stations"]) == {"142", "351", "1222"}
    assert any("3 Holfuy stations merged" in note for note in notes)


def test_a_failed_build_never_reaches_the_cache(tmp_path, fake_sleep):
    """The safety property: the shared cache is the thing matching reads, so a
    build that does not pass the gate must not touch it. The catalogue file is
    separate - it is the run's resume state."""
    countries = json.dumps([{"countryCode": "NO", "countryName": "Norway"}])
    directory = json.dumps([{"id": i, "name": f"S{i}"} for i in range(20)])
    fetcher = FakeFetcher(
        {holfuy.DIRECTORY_URL + "?countries": countries,
         holfuy.DIRECTORY_URL + "?country=NO": directory},
        default=_fixture(STATION_NO_MAP),
    )
    # The breaker trips after ten consecutive failures, before the gate.
    with pytest.raises(HolfuyCatalogueError):
        build(cache=Cache(path=tmp_path / "cache.json"), fetcher=fetcher,
              catalogue_path=tmp_path / "cat.json", clock=fake_sleep)

    assert not (tmp_path / "cache.json").exists()
    assert read_catalogue(tmp_path / "cat.json") == {}


def test_a_carried_over_catalogue_resumes_without_refetching(tmp_path, fake_sleep):
    """An interrupted build must resume, not re-walk 1,573 pages - the same
    property the WU probe loop has."""
    catalogue_path = tmp_path / "cat.json"
    holfuy.write_catalogue(catalogue_path, {
        "142": {"name": "THPK Ersfjord", "country": "NO", "country_name": "Norway",
                "lat": 69.70017, "lon": 18.63842, "alt": 130,
                "url": holfuy.station_url("142"),
                "source_page": holfuy.station_url("142"),
                "fetched_utc": "2026-01-01T00:00:00Z"},
    })

    fetcher = _build_fetcher()
    build(cache=Cache(path=tmp_path / "cache.json"), fetcher=fetcher,
          catalogue_path=catalogue_path, clock=fake_sleep,
          wall_clock=lambda: 1_789_000_000.0)

    # 142 was already known, so its page was never requested.
    assert holfuy.station_url("142") not in fetcher.calls
    assert holfuy.station_url("351") in fetcher.calls

    catalogue = read_catalogue(catalogue_path)
    # The carried entry keeps the date its coordinates were observed, not this
    # run's date; the newly fetched one takes this run's.
    assert catalogue["142"]["fetched_utc"] == "2026-01-01T00:00:00Z"
    assert catalogue["351"]["fetched_utc"] == "2026-09-10T00:26:40Z"


def test_refresh_rereads_every_page(tmp_path, fake_sleep):
    """--refresh-holfuy is the escape hatch for a moved or corrected station."""
    catalogue_path = tmp_path / "cat.json"
    holfuy.write_catalogue(catalogue_path, {
        "142": {"name": "stale", "lat": 0.0, "lon": 0.0,
                "fetched_utc": "2026-01-01T00:00:00Z"},
    })
    fetcher = _build_fetcher()
    catalogue = build(cache=Cache(path=tmp_path / "cache.json"), fetcher=fetcher,
                      catalogue_path=catalogue_path, clock=fake_sleep,
                      wall_clock=lambda: 1_789_000_000.0, refresh=True)

    assert holfuy.station_url("142") in fetcher.calls
    assert catalogue["142"]["lat"] == 69.70017  # the stale 0,0 is gone


def test_empty_directory_is_a_hard_failure_not_an_empty_catalogue(fake_sleep):
    fetcher = FakeFetcher({holfuy.DIRECTORY_URL + "?countries": "[]"})
    with pytest.raises(HolfuyCatalogueError, match="no countries"):
        fetch_catalogue(fetcher=fetcher, clock=fake_sleep)


def test_a_run_that_resolves_nothing_is_a_hard_failure(fake_sleep):
    """The plan's verification: prove the negative. When the map link is gone
    from every page, the build must fail loudly rather than publish an empty
    catalogue."""
    fetcher = FakeFetcher(
        {holfuy.DIRECTORY_URL + "?countries":
            json.dumps([{"countryCode": "NO", "countryName": "Norway"}]),
         holfuy.DIRECTORY_URL + "?country=NO":
            json.dumps([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])},
        default=_fixture(STATION_NO_MAP),
    )
    with pytest.raises(HolfuyCatalogueError, match="resolved no coordinates"):
        fetch_catalogue(fetcher=fetcher, clock=fake_sleep)


def test_a_second_build_reads_the_directory_but_no_station_page(tmp_path, fake_sleep):
    """Resume semantics: the directory is re-walked (that is how a new station
    is noticed, at ~93 index requests), but no station page is re-read."""
    fetcher = _build_fetcher()
    cache = Cache(path=tmp_path / "cache.json")
    build(cache=cache, fetcher=fetcher, catalogue_path=tmp_path / "cat.json",
          clock=fake_sleep, wall_clock=lambda: 1_789_000_000.0)
    assert any("/weather/" in url for url in fetcher.calls)  # station pages read

    fetcher.calls.clear()
    build(cache=Cache.load(tmp_path / "cache.json"), fetcher=fetcher,
          catalogue_path=tmp_path / "cat.json", clock=fake_sleep,
          wall_clock=lambda: 1_789_000_000.0)

    assert fetcher.calls  # the directory was walked
    assert not any("/weather/" in url for url in fetcher.calls)
    assert all(url.startswith(holfuy.DIRECTORY_URL) for url in fetcher.calls)


# --- the licensing gate ------------------------------------------------------


def test_default_invocation_does_not_touch_the_match_pool():
    """`--networks` defaulting to wu-pws is load-bearing: adding Holfuy must
    not change what an existing invocation does."""
    from scripts.wu_pws_stations import HOLFUY_PREVIEW_PATH, resolve_output
    from src.pws import OUTPUT_PATH

    path, preview = resolve_output(None, ("wu-pws",))
    assert (path, preview) == (OUTPUT_PATH, False)

    path, preview = resolve_output(None, ("wu-pws", "bom"))
    assert (path, preview) == (OUTPUT_PATH, False)


def test_a_holfuy_run_writes_the_preview_not_the_shipped_csv():
    """The licensing gate: until Holfuy agrees, its rows cannot land in
    app/site_weather_stations.csv, which ships to the app."""
    from scripts.wu_pws_stations import HOLFUY_PREVIEW_PATH, resolve_output
    from src.pws import OUTPUT_PATH

    path, preview = resolve_output(None, ("wu-pws", "bom", "holfuy"))
    assert preview is True
    assert path == HOLFUY_PREVIEW_PATH
    assert path != OUTPUT_PATH
    assert path.name == "site_weather_stations.holfuy-preview.csv"

    # An explicit --output still wins - the operator's decision, not ours.
    explicit, _ = resolve_output("tmp/out.csv", ("holfuy",))
    assert explicit == Path("tmp/out.csv")


def test_a_cached_holfuy_station_cannot_win_a_default_match(tmp_path):
    """The gate that the filename alone does not provide.

    Cache.nearest is source-blind, so once a Holfuy catalogue is merged a
    default run would otherwise match Holfuy stations and write them into the
    shipped CSV. The match pool is what keeps them out.
    """
    from src.pws import match_pool

    cache = Cache(path=tmp_path / "cache.json")
    # A Holfuy station 20 m from the launch, and a WU one 1.5 km away: if the
    # pool leaked, Holfuy would win on distance and reach the output.
    merge_into_cache(cache, {"142": {"lat": -31.85334, "lon": 116.76261}})
    cache.merge([Station("IBURGE35", -31.866, 116.76261, network="wu-pws")])

    launch = Site("ansg:1", "Bakewell", -31.85334, 116.76261, "256")

    default_pool = match_pool(cache, ("wu-pws",))
    assert "holfuy" not in default_pool
    hit = cache.nearest(launch.lat, launch.lon, pool=default_pool)
    assert hit[0].network == "wu-pws"

    row = match_row(launch, cache, "2026-09-11T00:00:00Z", pool=default_pool)
    assert row["obs_source"] == "wu-pws"
    assert row["obs_station_id"] == "IBURGE35"

    # Named explicitly, the nearer Holfuy station wins - the point of the
    # network being in the pool at all.
    asked_pool = match_pool(cache, ("wu-pws", "bom", "holfuy"))
    assert "holfuy" in asked_pool
    asked = match_row(launch, cache, "2026-09-11T00:00:00Z", pool=asked_pool)
    assert asked["obs_source"] == "holfuy"
    assert asked["obs_station_id"] == "142"


def test_cached_wu_and_bom_stay_in_the_pool_for_existing_invocations(tmp_path):
    """Adding a third network must not change what the first two do: a run
    that fetches only wu-pws still matches cached BOM stations, exactly as it
    always has."""
    from src.pws import match_pool

    cache = Cache(path=tmp_path / "cache.json")
    cache.merge([
        Station("94917", -42.8825, 147.3292, network="bom"),
        Station("IBURGE35", -31.85334, 116.76261, network="wu-pws"),
    ])
    pool = match_pool(cache, ("wu-pws",))
    assert pool == {"wu-pws", "bom"}
    assert "holfuy" not in pool
