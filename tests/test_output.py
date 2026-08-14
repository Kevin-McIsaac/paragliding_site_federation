"""Selection, the app CSV, and the review table."""

import csv
import pathlib

from src.canonical_store import write_app_csv, write_sites
from src.clustering import Cluster
from src.ids import IdRegistry
from src.clustering import ReviewItem, ReviewReason
from src.matcher import pair_for
from src.reports import name_similarity, render_review as render
from src.selection import select
from tests.conftest import metres, record


def _item(pair, reason=ReviewReason.BEYOND_THRESHOLD):
    return ReviewItem(pair, reason)


def _select(*members):
    return select(Cluster(members=members), IdRegistry())


def test_national_guide_supplies_name_and_position_in_its_own_country():
    au = record("ansg", "a", name="Yallingup - Rabbit Hill", lat=-33.71)
    pge = record("pge", "1", name="Rabbit Hill", lat=-33.70)

    site = _select(au, pge)

    assert site.primary == "ansg"
    assert site.name == "Yallingup - Rabbit Hill"
    assert site.lat == -33.71


def test_pge_wins_where_no_national_guide_covers_the_country():
    site = _select(record("pge", "1", country="FR", name="Chamonix"))
    assert site.primary == "pge"


def test_wind_falls_back_when_the_winner_has_none():
    """~26 Site Guide sites have conditions prose that does not parse."""
    au = record("ansg", "a", wind={})
    pge = record("pge", "1", wind={"N": 1, "NE": 2})

    site = _select(au, pge)

    assert site.primary == "ansg"
    assert site.wind == {"N": 1, "NE": 2}


def test_site_guide_wind_wins_when_present_losing_pge_gradation():
    """Accepted consequence: parsed prose can only say 'in range', so a Site
    Guide-primary launch never shows 'excellent' even if PGE rated it 2."""
    au = record("ansg", "a", wind={"S": 1})
    pge = record("pge", "1", wind={"N": 2})

    site = _select(au, pge)

    assert site.wind == {"S": 1}


def test_sources_records_every_contributor():
    site = _select(record("pge", "1"), record("ansg", "a"))
    assert site.sources == {"pge": "1", "ansg": "a"}


def test_app_csv_has_only_the_columns_the_app_needs(tmp_path):
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1"))], path)

    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert list(rows[0]) == [
        "id", "ref", "name", "longitude", "latitude", "altitude", "country",
        "wind_n", "wind_ne", "wind_e", "wind_se",
        "wind_s", "wind_sw", "wind_w", "wind_nw",
        "source", "closed",
        "site_type", "tow", "site_group", "notes", "primary",
    ]
    assert rows[0]["wind_n"] == "1" and rows[0]["wind_ne"] == "2"
    assert rows[0]["source"] == "pge:1"
    # A launch, unless a guide said otherwise - the column is never blank, so
    # the app never has to guess what a row without one is.
    assert rows[0]["site_type"] == "launch" and rows[0]["tow"] == "0"


def test_csv_header_is_pinned_to_the_apps_parser(tmp_path):
    """Pinned so a column cannot appear or vanish without someone deciding to.

    The old reason given here - that the app parses positionally, so an inserted
    column shifts every field after it - stopped being true when the app moved to
    reading by column name; `write_app_csv` says as much. What is still true is
    that latitude and longitude are adjacent and interchangeable in type, so
    swapping their *values* parses cleanly and puts every site in the wrong
    hemisphere, which no row count or import log would catch. That is what
    test_csv_writes_longitude_before_latitude covers, and this pins the shape it
    depends on.
    """
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1"))], path)

    assert path.read_text().splitlines()[0] == (
        "id,ref,name,longitude,latitude,altitude,country,"
        "wind_n,wind_ne,wind_e,wind_se,wind_s,wind_sw,wind_w,wind_nw,source,closed,"
        "site_type,tow,site_group,notes,primary"
    )


def test_csv_names_the_guide_whose_record_won(tmp_path):
    """A consumer showing a merged row beside its contributing guides has to be
    able to say whose figures it is showing, and `source` cannot: it names every
    guide that describes the launch, not the one selection picked.

    The app gave each guide a tab and introduced the catalogue's values as "this
    launch as DHV records it" - true on today's rows only by accident, and
    nothing on either side would have noticed it stop being true.
    """
    path = tmp_path / "sites.csv"
    au = record("ansg", "a", name="Yallingup - Rabbit Hill")
    pge = record("pge", "1", name="Rabbit Hill")
    write_app_csv([_select(au, pge)], path)

    row = next(csv.DictReader(path.read_text().splitlines()))
    assert row["primary"] == "ansg"
    assert row["name"] == "Yallingup - Rabbit Hill"
    assert set(row["source"].split(";")) == {"ansg:a", "pge:1"}


def test_csv_primary_is_never_blank(tmp_path):
    """A single-source row is primary to its only guide, so a consumer never has
    to decide what an empty one means."""
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1")), _select(record("dhv", "2-x"))], path)

    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert [r["primary"] for r in rows] == ["pge", "dhv"] or [
        r["primary"] for r in rows
    ] == ["dhv", "pge"]
    assert all(r["primary"] for r in rows)


def test_csv_primary_does_not_claim_a_gap_filled_altitude(tmp_path):
    """`primary` means name, wind and position - not every field on the row.

    Altitude and notes fall back to a losing guide when the winner published
    none, so a consumer reading this as "every figure here is DHV's" would state
    something the catalogue never said. Pinned because the wording of that claim
    lives in another repository.
    """
    path = tmp_path / "sites.csv"
    winner = record("ansg", "a", altitude=None)
    loser = record("pge", "1", altitude=436)
    write_app_csv([_select(winner, loser)], path)

    row = next(csv.DictReader(path.read_text().splitlines()))
    assert row["primary"] == "ansg"
    assert row["altitude"] == "436"


def test_published_catalogue_names_a_contributing_guide_on_every_row():
    """Over the artifact itself, not a fixture.

    The app reads `primary` to say whose figures a merged row is showing. Two
    things have to hold for that to be safe on every row, and neither is visible
    from a two-record unit test: it is never blank, and it always names a guide
    that actually contributed - a primary absent from `source` would have the app
    attribute the row to a guide it never lists.
    """
    import io

    published = pathlib.Path(__file__).resolve().parents[1] / "app/sites.csv"
    # StringIO rather than splitlines(): guide prose contains hard line breaks,
    # and splitlines drops the terminators, so quoted fields come back flattened.
    rows = list(csv.DictReader(io.StringIO(published.read_text(encoding="utf-8"))))

    assert len(rows) > 11000, "a sweep over nothing is not coverage"

    blank = [r["ref"] for r in rows if not r.get("primary")]
    assert not blank, f"{len(blank)} rows name no primary, e.g. {blank[:3]}"

    stranded = [
        r["ref"]
        for r in rows
        if r["primary"] not in {t.split(":", 1)[0] for t in r["source"].split(";") if t}
    ]
    assert not stranded, f"primary is not a contributor on {stranded[:3]}"


def test_csv_writes_longitude_before_latitude(tmp_path):
    """Guards the swap specifically, not just the header text."""
    path = tmp_path / "sites.csv"
    site = record("pge", "1", lat=-33.7, lon=151.3)
    write_app_csv([_select(site)], path)

    row = list(csv.DictReader(path.read_text().splitlines()))[0]
    assert float(row["latitude"]) == -33.7
    assert float(row["longitude"]) == 151.3


def test_csv_id_is_the_numeric_part_of_the_canonical_id(tmp_path):
    """pge_sites.id is INTEGER PRIMARY KEY; PSF-000001 would not fit."""
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1"))], path)
    assert list(csv.DictReader(path.read_text().splitlines()))[0]["id"] == "1"


def test_csv_carries_altitude_and_lowercase_country(tmp_path):
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1", altitude=341.0, country="GB"))], path)

    row = list(csv.DictReader(path.read_text().splitlines()))[0]
    assert row["altitude"] == "341"
    assert row["country"] == "gb"  # matches the asset it replaces


def test_csv_altitude_is_empty_when_no_source_has_it(tmp_path):
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1", altitude=None))], path)
    assert list(csv.DictReader(path.read_text().splitlines()))[0]["altitude"] == ""


def test_app_csv_quotes_names_containing_commas(tmp_path):
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1", name="Canberra, Lanyon"))], path)
    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert rows[0]["name"] == "Canberra, Lanyon"


def test_app_csv_rewrite_is_idempotent(tmp_path):
    path = tmp_path / "sites.csv"
    sites = [_select(record("pge", "1"))]
    assert write_app_csv(sites, path) is True
    assert write_app_csv([_select(record("pge", "1"))], path) is False


def test_country_json_is_sharded_and_idempotent(tmp_path):
    registry = IdRegistry()
    sites = [
        select(Cluster((record("pge", "1", country="AU"),)), registry),
        select(Cluster((record("pge", "2", country="FR"),)), registry),
    ]
    write_sites(sites, tmp_path)
    assert (tmp_path / "au.json").exists() and (tmp_path / "fr.json").exists()

    counts = write_sites(sites, tmp_path)
    assert counts["written"] == 0 and counts["unchanged"] == 2


def test_review_table_has_the_requested_columns_and_order():
    pge = record("pge", "1", name="Cape Jervis")
    near = record("ansg", "a", name="Cape Jervis SG", lat=-33.7 - metres(120))
    far = record("ansg", "b", name="Shoreham SG", lat=-33.7 - metres(240))

    table = render([_item(pair_for(pge, far)), _item(pair_for(pge, near))])
    lines = [l for l in table.splitlines() if l.startswith("|")]

    # Columns are named by position, not by guide: a pair can be any two
    # guides now, and addressing them as (pge, ansg) rendered a third as blank.
    assert lines[0] == "| Site A | Site B | Distance | Name match | Why | Override (to merge) |"
    assert "Cape Jervis SG" in lines[2]  # closest first
    assert "Shoreham SG" in lines[3]


def test_identical_names_score_full_similarity():
    pge = record("pge", "1", name="Cape Jervis")
    au = record("ansg", "a", name="Cape Jervis", lat=-33.7 - metres(120))
    assert "| 100% |" in render([_item(pair_for(pge, au))])


def test_site_prefixed_name_is_not_penalised():
    """Site Guide qualifies launches with their site, so one name is a
    superset of the other - that must not read as a poor match."""
    pge = record("pge", "1", name="Honeysuckle")
    au = record("ansg", "a", name="Honeysuckle - Launch 3", lat=-33.7 - metres(120))
    assert "| 100% |" in render([_item(pair_for(pge, au))])


def test_genuinely_different_names_score_low():
    pge = record("pge", "1", name="Thirteenth Beach")
    au = record("ansg", "a", name="Barwon Heads - PG beach launch 30W",
                lat=-33.7 - metres(120))

    similarity = name_similarity(pge, au)

    assert similarity < 60, f"expected a low score, got {similarity}"


def test_review_names_link_to_their_source_page():
    pge = record("pge", "1", name="Cape Jervis", url="https://www.paraglidingearth.com/?site=1")
    au = record("ansg", "a", name="Cape Jervis SG",
                lat=-33.7 - metres(120), url="https://siteguide.org.au/sites/9")

    table = render([_item(pair_for(pge, au))])

    assert "[Cape Jervis](https://www.paraglidingearth.com/?site=1)" in table
    assert "[Cape Jervis SG](https://siteguide.org.au/sites/9)" in table


def test_review_falls_back_to_plain_name_without_a_url():
    pge = record("pge", "1", name="Cape Jervis", url=None)
    au = record("ansg", "a", lat=-33.7 - metres(120), url=None)
    # The guide is named in the cell, so a reader can tell which side is which
    # without the column heading doing it.
    assert "| **pge** Cape Jervis |" in render([_item(pair_for(pge, au))])


def test_pipe_in_a_name_cannot_break_the_table():
    pge = record("pge", "1", name="Bald | Hill", url=None)
    au = record("ansg", "a", lat=-33.7 - metres(120), url=None)
    assert r"Bald \| Hill" in render([_item(pair_for(pge, au))])


def test_report_leads_with_merged_and_unmerged_counts():
    pge = record("pge", "1")
    au = record("ansg", "a", lat=-33.7 - metres(120))

    table = render([_item(pair_for(pge, au))], merged=61)

    assert "**61** merged automatically" in table
    assert "**1** left unmerged but close" in table


def test_counts_are_omitted_when_merge_total_is_unknown():
    assert "merged automatically" not in render([])


def test_a_closed_site_is_kept_and_flagged(tmp_path):
    """Dropping closed sites left the other guides' entries for the same place
    on the map as ordinary launches, with nothing to say it was shut - making
    the merged dataset less safe than either source alone."""
    path = tmp_path / "sites.csv"
    shut = record("ansg", "a", closed="Closed awaiting a council agreement")

    write_app_csv([_select(shut)], path)

    row = list(csv.DictReader(path.read_text().splitlines()))[0]
    assert row["closed"] == "Closed awaiting a council agreement"


def test_one_guide_calling_a_site_closed_is_enough(tmp_path):
    """The warning must survive even when the guide that raised it lost every
    other field to a higher-ranked source."""
    au = record("ansg", "a", closed="Closed: council agreement pending")
    pge = record("pge", "1", name="Still listed as open", closed=None)

    site = _select(au, pge)
    assert site.closed == "Closed: council agreement pending"

    other_way = _select(pge, au)
    assert other_way.closed == "Closed: council agreement pending"


def test_an_open_site_has_an_empty_closed_field(tmp_path):
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1"))], path)
    assert list(csv.DictReader(path.read_text().splitlines()))[0]["closed"] == ""
