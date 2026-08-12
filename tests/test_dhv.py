"""The DHV adapter, against a fixture cut from the real export.

This is the first adapter with parsing tests, and it earns them: unlike the
other two sources, everything but the coordinates has to be recovered from a
prose description written in German, and the ref has to be manufactured because
DHV publishes no per-launch id.
"""

from pathlib import Path

from src.sources.dhv import DhvSource, _slug, parse_kml

FIXTURE = Path(__file__).parent / "fixtures" / "dhv_sample.kml"
BBOX = DhvSource.bbox


def records():
    return parse_kml(FIXTURE.read_text(), "DE", BBOX)


def by_name(name):
    return next(r for r in records() if r.name == name)


def test_landings_are_not_launches():
    """DHV publishes ~1,300 Landeplätze. The catalogue's unit is a launch, and
    the app would draw every one of them as a site you can take off from."""
    assert "Criesbach Landeplatz" not in [r.name for r in records()]


def test_tow_fields_are_launches():
    """A third of the German data, and PGE carries almost none of it."""
    assert by_name("Ailringen").role == "launch"


def test_a_gelaende_with_several_takeoffs_gives_each_its_own_ref():
    """The failure this guards: all five Loser takeoffs share item=1416, so
    keying on the Gelände id alone would collapse them into one launch."""
    loser = [r for r in records() if r.id.startswith("1416-")]

    assert len(loser) == 2
    assert len({r.key for r in loser}) == 2
    assert {r.key for r in loser} == {
        "dhv:1416-loser-startplatz-1",
        "dhv:1416-loser-startplatz-3-braeuningalm",
    }


def test_siblings_share_a_group_so_they_are_never_reported_as_duplicates():
    assert {r.group_id for r in records() if r.id.startswith("1416-")} == {"1416"}


def test_german_compass_points_become_english_ones():
    """Startrichtung is Ost, not East - so an unconverted "O" parses as nothing
    and the launch silently ships with no wind at all."""
    assert set(by_name("Loser Startplatz 1").wind) == {"E", "W"}


def test_a_narrow_range_does_not_spread_across_the_compass():
    """SSO-SSW is a 45 degree arc centred on south, so on the app's 8-point
    compass it is S and nothing else. Widening it would advertise the site as
    flyable in SE and SW, which DHV did not say."""
    assert set(by_name("Criesbach Startplatz 1").wind) == {"S"}


def test_a_range_takes_the_shorter_arc():
    """NW-N is NW->N, not the long way round through S."""
    assert set(by_name("Loser Startplatz 3 Bräuningalm").wind) == {"NW", "N"}


def test_wind_is_in_range_not_graded():
    assert set(by_name("Criesbach Startplatz 1").wind.values()) == {1}


def test_a_launch_with_no_startrichtung_still_ships():
    """9 of 1,832 have none. Dropping them would lose the launch entirely."""
    quiet = by_name("Namenlos ohne Startrichtung")
    assert quiet.wind == {} and quiet.altitude is None


def test_altitude_and_url_come_from_the_description():
    site = by_name("Criesbach Startplatz 1")
    assert site.altitude == 350.0
    assert site.url == (
        "https://service.dhv.de/db2/details.php?qi=glp_details&item=5701"
    )


def test_coordinates_are_read_lon_then_lat():
    """KML is lon,lat. Swapping them parses cleanly and puts every site in the
    wrong place - the same trap the CSV column order carries a warning about."""
    site = by_name("Criesbach Startplatz 1")
    assert (round(site.lat, 4), round(site.lon, 4)) == (49.31, 9.6289)


def test_records_outside_the_box_are_dropped():
    assert "Weit weg" not in [r.name for r in records()]


def test_slug_folds_umlauts_deterministically():
    assert _slug("Bräuningalm Startplatz 3") == "braeuningalm-startplatz-3"
    assert _slug("Hochhamm  Startplatz!") == "hochhamm-startplatz"
