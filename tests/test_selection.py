"""Whole-record selection with gap-fill.

The wind-direction test is the important one: Site Guide AU publishes no
orientation data, and the app feeds windDirections into its flyability
calculation. Strict whole-record selection would blank it out on every
enriched Australian site.
"""

from src.clustering import Cluster
from src.ids import IdRegistry
from src.selection import select
from tests.conftest import record


def _select(*members):
    return select(Cluster(members=members), IdRegistry())


def test_national_guide_wins_in_its_own_country():
    site = _select(record("pge", "1", name="PGE name"), record("siteguide_au", "a", name="SG name"))
    assert site.primary == "siteguide_au"
    assert site.values["name"] == "SG name"


def test_pge_wins_outside_a_national_guides_scope():
    site = _select(record("pge", "1", country="FR", name="PGE name"))
    assert site.primary == "pge"


def test_wind_directions_are_gap_filled_from_pge():
    sg = record("siteguide_au", "a", orientation=frozenset())  # no wind data at all
    pge = record("pge", "1", orientation=frozenset({"N", "NE"}))

    site = _select(sg, pge)

    assert site.primary == "siteguide_au"
    assert site.values["orientation"] == ["N", "NE"]
    assert site.field_sources["orientation"] == "pge"


def test_winners_own_values_are_not_marked_as_gap_filled():
    site = _select(record("siteguide_au", "a", hazards="Powerlines"), record("pge", "1"))
    assert site.values["hazards"] == "Powerlines"
    assert "hazards" not in site.field_sources


def test_sources_records_every_contributing_provider():
    site = _select(record("pge", "1"), record("siteguide_au", "a"))
    assert site.sources == {"pge": "1", "siteguide_au": "a"}


def test_single_source_cluster_is_normal():
    site = _select(record("pge", "1"))
    assert site.primary == "pge"
    assert site.sources == {"pge": "1"}
    assert site.field_sources == {}


def test_orientation_serializes_as_a_sorted_list():
    site = _select(record("pge", "1", orientation=frozenset({"NW", "N", "NE"})))
    assert site.values["orientation"] == ["N", "NE", "NW"]
