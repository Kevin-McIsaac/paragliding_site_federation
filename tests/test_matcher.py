"""The distance bands: merge under 100m, review to 250m, ignore beyond."""

from src.matcher import Band, pair_for, pairs
from tests.conftest import metres, record


def _at(distance_m, **overrides):
    return record("siteguide_au", "a", lat=-33.7 - metres(distance_m), **overrides)


def test_under_100m_merges():
    pair = pair_for(record("pge", "1"), _at(60))
    assert pair.band is Band.MERGE


def test_between_100m_and_250m_is_reviewed():
    pair = pair_for(record("pge", "1"), _at(180))
    assert pair.band is Band.REVIEW


def test_beyond_250m_is_not_a_pair_at_all():
    assert pair_for(record("pge", "1"), _at(400)) is None


def test_boundaries():
    assert pair_for(record("pge", "1"), _at(99)).band is Band.MERGE
    assert pair_for(record("pge", "1"), _at(101)).band is Band.REVIEW
    assert pair_for(record("pge", "1"), _at(249)).band is Band.REVIEW
    assert pair_for(record("pge", "1"), _at(251)) is None


def test_same_source_is_never_compared():
    """One guide listing several launches at a site is deliberate, not a
    duplicate - Mt Borah's four launches must all survive."""
    assert pair_for(record("siteguide_au", "a"), record("siteguide_au", "b")) is None


def test_landing_never_matches_launch():
    assert pair_for(record("pge", "1", role="launch"), _at(10, role="landing")) is None


def test_nothing_but_distance_is_considered():
    """Names, wind and everything else are irrelevant to the decision."""
    unrelated = _at(60, name="Completely Different", wind={"S": 1})
    assert pair_for(record("pge", "1"), unrelated).band is Band.MERGE


def test_approximate_coordinates_are_reviewed_never_merged():
    """Sites whose published position is a placeholder cannot evidence a
    merge, however close they happen to land."""
    obfuscated = _at(20, approximate_location=True)
    assert pair_for(record("pge", "1"), obfuscated).band is Band.REVIEW


def test_spatial_index_finds_pairs_across_cell_boundaries():
    a = record("pge", "1", lat=-33.70999)
    b = record("siteguide_au", "a", lat=-33.71001)  # different cell, ~2m apart
    found = list(pairs([a, b]))
    assert len(found) == 1 and found[0].band is Band.MERGE


def test_each_pair_is_yielded_once():
    recs = [record("pge", "1"), record("siteguide_au", "a"), record("siteguide_au", "b", lat=-33.7001)]
    found = list(pairs(recs))
    assert len({p.keys for p in found}) == len(found)
