"""The FFVL adapter, against a fixture shaped like the real export.

Unlike the other sources, everything here is recovered from one JSON file
written in French: the role from the sous-type, the wind from an 8-point
French compass written O for West, and the country from the postcode - which
for the DOM is the only French thing about the row. The fixture is synthetic
but shaped exactly like the schema, poison rows included, because the real
file sits behind an API key that does not exist yet.
"""

import logging
from pathlib import Path

import httpx
import pytest

from src.model import AUSTRALIA_BBOX, BoundingBox, intersect
from src.sources.ffvl import FfvlSource, FfvlSourceError, parse_sites

FIXTURE = Path(__file__).parent / "fixtures" / "ffvl_sample.json"
BBOX = FfvlSource.bbox

#: The live endpoint's answer without a key, verbatim (90 bytes). Never
#: paraphrased in the test: the error message quotes it back.
GATE = (
    "This data is now available using an FFVL API key "
    "to be requested at : informatique@ffvl.fr"
)


def records():
    return parse_sites(FIXTURE.read_text(), BBOX)


def by_name(name):
    return next(r for r in records() if r.name == name)


def test_a_landing_is_a_landing():
    """The app filters on this. A landing typed as a launch would be offered as
    somewhere to take off from, and could capture a logged flight."""
    landing = by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LES REMBLAIS")
    assert landing.role == "landing"
    assert landing.tow is False


def test_a_landing_carries_its_terrain_so_it_can_find_its_launches():
    """Launches and landings of one terrain hang from the terrain id - the only
    usable join, and the reason the record's own numero is not it."""
    landing = by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LES REMBLAIS")
    launch = by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LE CREY DU MIDI")
    assert landing.group_ids == launch.group_ids == ("73050",)
    assert launch.key == "ffvl:73D050A" and landing.key == "ffvl:73A050A"


def test_a_landing_ignores_its_wind():
    """FFVL publishes an arc on landings too - 620 of 752 did in 2022 - so an
    empty wind here is a decision, not absence. Selection zeroes landing wind
    regardless; parsing it would only invite it to leak into a launch."""
    assert by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LES REMBLAIS").wind == {}


def test_the_french_compass_becomes_the_english_one():
    """O is Ouest, SO is Sud-Ouest, NO is Nord-Ouest. An unconverted O parses
    as nothing and the launch silently ships with no wind at all."""
    assert set(by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LES GRATTAVOL")
               .wind) == {"W", "NW"}


def test_a_comma_separated_arc_still_parses():
    """One record in the real file separates with commas; both forms accepted."""
    assert set(by_name("SAINT MICHEL DE CHAILLOL - LE PETIT RENARD").wind) == {
        "N", "NE", "SE", "S", "SW", "NW",
    }


def test_wind_is_in_range_not_graded():
    assert all(v == 1 for r in records() for v in r.wind.values())


def test_a_launch_with_no_wind_and_no_altitude_still_ships():
    """486 rows carry date_modification 0000-00-00 and many leave alt blank -
    neither is a parse failure, and dropping the launch would lose it."""
    quiet = by_name("DIGNE LES BAINS")
    assert quiet.wind == {} and quiet.altitude is None


def test_tow_platforms_are_launches_that_say_so():
    tow = by_name("SAINT HILAIRE DU TOUVET - PLATEFORME DU LANCENT")
    assert tow.role == "launch" and tow.tow is True


def test_a_hill_launch_is_not_a_tow():
    assert by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LE CREY DU MIDI").tow is False


def test_the_practice_filter_reads_every_practice_not_the_first():
    """A site that also lists kite keeps its place: the type is about the
    place, the practices are about what you do there."""
    assert by_name("SAINT PABU - TREZ AR LANNOU").country == "FR"


def test_kite_and_snowkite_sites_are_not_sites():
    """~9% of the real file, none of it launchable with a paraglider."""
    names = [r.name for r in records()]
    assert "SAINT AYGULF - PLAGE DE LA GAUTHIERE" not in names
    assert "COL DU LAUTARET - PLATEAU DU GLEYZIN" not in names


def test_speed_riding_only_is_dropped():
    """Dropped by the practice filter while its sous-type says Décollage - the
    filter decides, not the type."""
    assert "LES ARCS - AIGUILLE ROUGE" not in [r.name for r in records()]


def test_an_unknown_sous_type_is_dropped_loudly(caplog):
    """An unmapped type with kept practices must not pass in silence."""
    with caplog.at_level(logging.WARNING):
        names = [r.name for r in records()]
    assert "ROULAGE DE TEST" not in names
    assert "Roulage" in caplog.text


def test_an_interdiction_is_kept_and_says_so():
    """Dropping it left the other guides' entries for the same hill looking
    ordinary; keeping it with `closed` is the point of the closed column."""
    forbidden = by_name("MONTS DU MATIN - LA FAREE")
    assert forbidden.role == "launch"
    assert forbidden.closed == "Site interdit par arrete municipal du 12 mai"


def test_a_record_with_no_id_is_dropped_loudly(caplog):
    """One kept row in the real file has neither numero nor terrain id."""
    with caplog.at_level(logging.WARNING):
        assert "PLAGE DU BOUIL" not in [r.name for r in records()]
    assert "PLAGE DU BOUIL" in caplog.text


def test_a_numero_shared_by_two_terrains_drops_both(caplog):
    """The one upstream collision (two Corsican terrains, one numero). Keeping
    either would key two launches alike, which no ref may do."""
    with caplog.at_level(logging.WARNING):
        names = [r.name for r in records()]
    assert "SANT ANDREA DI COTONE - PUNTA DI CAMPO MORO" not in names
    assert "CUTTOLI CORTICCHIATO - COL DE SARRO" not in names
    assert "20D009A" in caplog.text


def test_postcodes_map_to_the_countries_the_catalogue_shards():
    """Métropole, Corsica and each DOM publish under their own country, read
    from the postcode alone - it is the only French thing on a Réunion row."""
    assert by_name("SAINT LEU - LA POINTUE").country == "RE"
    assert by_name("PAPEETE - TAAONE").country == "PF"
    assert by_name("SAINT PIERRE - ANSE TURIN").country == "MQ"
    assert by_name("LUMIO - CHAPELLE SANTA RAGINA").country == "FR"
    assert by_name("SAINT FRANCOIS LONGCHAMP - EPIERRE - LE CREY DU MIDI") \
        .country == "FR"


def test_a_postcode_that_maps_nowhere_is_dropped_loudly(caplog):
    """Monaco's 980: kept silently it would publish a row no country shard
    holds, so it goes - but a named warning, not a shrug."""
    with caplog.at_level(logging.WARNING):
        assert "MONACO - TIPOULOU" not in [r.name for r in records()]
    assert "98000" in caplog.text


def test_a_site_outside_every_box_is_dropped():
    """A world-spanning box would have swallowed Australia; the tuple of
    boxes is what keeps `--scope au` from fetching this source."""
    assert "BONDI BEACH - NORTH BONDI" not in [r.name for r in records()]


def test_a_nameless_site_falls_back_to_its_place_name():
    assert by_name("SILLON DE SABLE").name == "SILLON DE SABLE"


def test_a_sous_nom_that_repeats_the_nom_is_not_doubled():
    assert by_name("DIGNE LES BAINS").name == "DIGNE LES BAINS"


def test_keys_are_distinct_and_prefixed():
    keys = [r.key for r in records()]
    assert len(keys) == len(set(keys)) == 13
    assert all(k.startswith("ffvl:") for k in keys)


def test_every_url_points_at_the_terrain_page():
    """The fiche answers on the terrain id - the one in `site_group` - so the
    record's own numero never appears in a URL."""
    for r in records():
        assert r.url == (
            f"https://federation.ffvl.fr/sites_pratique/voir/{r.group_ids[0]}"
        )


def test_the_boxes_are_a_tuple_and_leave_australia_alone():
    """A single box round métropole and DOM would span half the planet and
    break `--scope au`; the tuple must never overlap it."""
    assert isinstance(BBOX, tuple) and len(BBOX) == 6
    assert all(isinstance(b, BoundingBox) for b in BBOX)
    assert intersect(BBOX, AUSTRALIA_BBOX) is None


def test_the_gate_notice_raises_rather_than_parsing_to_nothing():
    """Zero records reads as an outage to the health gate; the gate notice is
    not an outage but a configuration the run cannot recover from, so it must
    stop the run with the reason, not ship an empty catalogue."""
    with pytest.raises(FfvlSourceError) as raised:
        parse_sites(GATE, BBOX)
    message = str(raised.value)
    assert "FFVL_API_KEY" in message
    assert "informatique@ffvl.fr" in message
    assert "requested at : informatique@ffvl.fr" in message  # the body, quoted back


def test_anything_that_is_not_the_sites_list_raises():
    with pytest.raises(FfvlSourceError):
        parse_sites("{}", BBOX)
    with pytest.raises(FfvlSourceError):
        parse_sites("<html>Service Unavailable</html>", BBOX)


def test_fetch_reads_the_offline_seam_without_the_network(monkeypatch):
    monkeypatch.setenv("FFVL_SITES_PATH", str(FIXTURE))
    source = FfvlSource(client=_fail_on_get_client())
    assert len(source.fetch(BBOX)) == len(records())


def test_fetch_sends_the_key_as_a_query_param(monkeypatch):
    monkeypatch.setenv("FFVL_API_KEY", "secret-key")
    source = FfvlSource(client=_mock_client(
        lambda request: _assert_param(request, "apikey", "secret-key")))
    assert len(source.fetch(BBOX)) == len(records())


def test_fetch_without_a_key_asks_plain(monkeypatch):
    monkeypatch.delenv("FFVL_API_KEY", raising=False)
    source = FfvlSource(client=_mock_client(
        lambda request: _assert_param(request, "apikey", None)))
    assert len(source.fetch(BBOX)) == len(records())


def test_the_adapter_is_ready_to_publish():
    """The gates the pipeline and guides.json run before a fetch - satisfied
    here so activation is a registration line, not a scramble."""
    assert FfvlSource.label and FfvlSource.full_name
    assert FfvlSource.homepage.startswith("https://")
    assert "{id}" in FfvlSource.site_url_template
    assert FfvlSource.site_url_template.format(id="73050") == (
        "https://federation.ffvl.fr/sites_pratique/voir/73050"
    )
    assert bool(FfvlSource.licence) == bool(FfvlSource.licence_url)


def _fail_on_get_client():
    class Fails:
        def get(self, *args, **kwargs):
            raise AssertionError("FFVL_SITES_PATH is set; the network is not wanted")
    return Fails()


def _mock_client(assertion):
    def handler(request: httpx.Request) -> httpx.Response:
        assertion(request)
        return httpx.Response(200, text=FIXTURE.read_text())
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)


def _assert_param(request: httpx.Request, name: str, value: str | None):
    if value is None:
        assert name not in request.url.params, f"{name} sent without a key"
    else:
        assert request.url.params[name] == value
        assert request.url.host == "data.ffvl.fr"