"""Clustering must be conservative: no transitive fusion, and rejections stick."""

from src.clustering import cluster
from src.matcher import Band, scored_pairs
from tests.conftest import record


def _cluster(records, rejected=None):
    return cluster(records, list(scored_pairs(records)), rejected=rejected)


def test_two_matching_records_form_one_cluster():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a")])
    assert len(result.clusters) == 1
    assert len(result.clusters[0].members) == 2


def test_unrelated_records_stay_separate():
    far = record("siteguide_au", "a", lat=-34.5, lon=150.0)
    result = _cluster([record("pge", "1"), far])
    assert len(result.clusters) == 2
    assert all(len(c.members) == 1 for c in result.clusters)


def test_transitive_link_does_not_fuse_three_records():
    """A~B and B~C both clear the bar, A~C does not: must NOT become one site.

    Three collinear launches ~200m apart, identical in every other respect, so
    distance alone decides. A-B and B-C score 0.82 (auto-link), A-C only 0.64.
    Naive union-find would chain them into a single site; conservative
    clustering must refuse the second merge and surface it for review instead.

    Three distinct providers, because same-provider pairs are never compared -
    with only two sources the guard would appear to work for the wrong reason.
    """
    a = record("pge", "1", lat=-33.7000)
    b = record("siteguide_au", "a", lat=-33.7018)
    c = record("dhv", "x", lat=-33.7036)

    result = _cluster([a, b, c])

    sizes = sorted(len(cl.members) for cl in result.clusters)
    assert sizes == [1, 2], f"expected a pair and a single, got {sizes}"
    assert result.review, "the blocked transitive link should be surfaced"


def test_rejected_pair_is_never_merged():
    a, b = record("pge", "1"), record("siteguide_au", "a")
    rejected = {frozenset({a.key, b.key})}

    result = _cluster([a, b], rejected=rejected)

    assert len(result.clusters) == 2
    assert result.review == []


def test_near_miss_becomes_a_review_item():
    """Close and similarly named, but far enough apart and differing on
    altitude to land in the flagged band rather than merging outright."""
    a = record("pge", "1", altitude=200.0)
    b = record("siteguide_au", "a", lat=-33.7027, altitude=300.0)

    result = _cluster([a, b])

    assert len(result.clusters) == 2
    assert len(result.review) == 1
    assert result.review[0].band in (Band.FLAGGED, Band.CANDIDATE)
