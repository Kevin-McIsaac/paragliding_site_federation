"""Selection, the app CSV, and the review table."""

import csv

from src.canonical_store import write_app_csv, write_sites
from src.clustering import Cluster
from src.ids import IdRegistry
from src.matcher import pair_for
from src.reports import name_similarity, render_review as render
from src.selection import select
from tests.conftest import metres, record


def _select(*members):
    return select(Cluster(members=members), IdRegistry())


def test_national_guide_supplies_name_and_position_in_its_own_country():
    au = record("siteguide_au", "a", name="Yallingup - Rabbit Hill", lat=-33.71)
    pge = record("pge", "1", name="Rabbit Hill", lat=-33.70)

    site = _select(au, pge)

    assert site.primary == "siteguide_au"
    assert site.name == "Yallingup - Rabbit Hill"
    assert site.lat == -33.71


def test_pge_wins_where_no_national_guide_covers_the_country():
    site = _select(record("pge", "1", country="FR", name="Chamonix"))
    assert site.primary == "pge"


def test_wind_falls_back_when_the_winner_has_none():
    """~26 Site Guide sites have conditions prose that does not parse."""
    au = record("siteguide_au", "a", wind={})
    pge = record("pge", "1", wind={"N": 1, "NE": 2})

    site = _select(au, pge)

    assert site.primary == "siteguide_au"
    assert site.wind == {"N": 1, "NE": 2}


def test_site_guide_wind_wins_when_present_losing_pge_gradation():
    """Accepted consequence: parsed prose can only say 'in range', so a Site
    Guide-primary launch never shows 'excellent' even if PGE rated it 2."""
    au = record("siteguide_au", "a", wind={"S": 1})
    pge = record("pge", "1", wind={"N": 2})

    site = _select(au, pge)

    assert site.wind == {"S": 1}


def test_sources_records_every_contributor():
    site = _select(record("pge", "1"), record("siteguide_au", "a"))
    assert site.sources == {"pge": "1", "siteguide_au": "a"}


def test_app_csv_has_only_the_columns_the_app_needs(tmp_path):
    path = tmp_path / "sites.csv"
    write_app_csv([_select(record("pge", "1"))], path)

    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert list(rows[0]) == [
        "id", "name", "latitude", "longitude",
        "wind_n", "wind_ne", "wind_e", "wind_se",
        "wind_s", "wind_sw", "wind_w", "wind_nw",
        "source",
    ]
    assert rows[0]["wind_n"] == "1" and rows[0]["wind_ne"] == "2"
    assert rows[0]["source"] == "pge:1"


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
    near = record("siteguide_au", "a", name="Cape Jervis SG", lat=-33.7 - metres(120))
    far = record("siteguide_au", "b", name="Shoreham SG", lat=-33.7 - metres(240))

    table = render([pair_for(pge, far), pair_for(pge, near)])
    lines = [l for l in table.splitlines() if l.startswith("|")]

    assert lines[0] == "| PGE Name | AU Name | Distance | Name match |"
    assert "Cape Jervis SG" in lines[2]  # closest first
    assert "Shoreham SG" in lines[3]


def test_identical_names_score_full_similarity():
    pge = record("pge", "1", name="Cape Jervis")
    au = record("siteguide_au", "a", name="Cape Jervis", lat=-33.7 - metres(120))
    assert "| 100% |" in render([pair_for(pge, au)])


def test_site_prefixed_name_is_not_penalised():
    """Site Guide qualifies launches with their site, so one name is a
    superset of the other - that must not read as a poor match."""
    pge = record("pge", "1", name="Honeysuckle")
    au = record("siteguide_au", "a", name="Honeysuckle - Launch 3", lat=-33.7 - metres(120))
    assert "| 100% |" in render([pair_for(pge, au)])


def test_genuinely_different_names_score_low():
    pge = record("pge", "1", name="Thirteenth Beach")
    au = record("siteguide_au", "a", name="Barwon Heads - PG beach launch 30W",
                lat=-33.7 - metres(120))

    similarity = name_similarity(pge, au)

    assert similarity < 60, f"expected a low score, got {similarity}"


def test_review_names_link_to_their_source_page():
    pge = record("pge", "1", name="Cape Jervis", url="https://www.paraglidingearth.com/?site=1")
    au = record("siteguide_au", "a", name="Cape Jervis SG",
                lat=-33.7 - metres(120), url="https://siteguide.org.au/sites/9")

    table = render([pair_for(pge, au)])

    assert "[Cape Jervis](https://www.paraglidingearth.com/?site=1)" in table
    assert "[Cape Jervis SG](https://siteguide.org.au/sites/9)" in table


def test_review_falls_back_to_plain_name_without_a_url():
    pge = record("pge", "1", name="Cape Jervis", url=None)
    au = record("siteguide_au", "a", lat=-33.7 - metres(120), url=None)
    assert "| Cape Jervis |" in render([pair_for(pge, au)])


def test_pipe_in_a_name_cannot_break_the_table():
    pge = record("pge", "1", name="Bald | Hill", url=None)
    au = record("siteguide_au", "a", lat=-33.7 - metres(120), url=None)
    assert r"Bald \| Hill" in render([pair_for(pge, au)])


def test_report_leads_with_merged_and_unmerged_counts():
    pge = record("pge", "1")
    au = record("siteguide_au", "a", lat=-33.7 - metres(120))

    table = render([pair_for(pge, au)], merged=61)

    assert "**61** merged automatically" in table
    assert "**1** left unmerged but close" in table


def test_counts_are_omitted_when_merge_total_is_unknown():
    assert "merged automatically" not in render([])
