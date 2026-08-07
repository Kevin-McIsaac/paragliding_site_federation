"""Clustering stays conservative and honours rejections."""

from src.clustering import cluster
from src.matcher import Band, pairs
from tests.conftest import metres, record


def _cluster(records, rejected=None):
    return cluster(records, list(pairs(records)), rejected=rejected)


def test_close_pair_forms_one_cluster():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a", lat=-33.7 - metres(50))])
    assert len(result.clusters) == 1
    assert len(result.clusters[0].members) == 2


def test_distant_records_stay_separate():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a", lat=-34.5)])
    assert len(result.clusters) == 2


def test_transitive_chain_does_not_fuse_three_records():
    """A-B 90m and B-C 90m, but A-C 180m: must not become one launch.

    Three providers, because same-source pairs are never compared and with
    only two the guard would appear to work for the wrong reason.
    """
    a = record("pge", "1", lat=-33.7)
    b = record("siteguide_au", "a", lat=-33.7 - metres(90))
    c = record("dhv", "x", lat=-33.7 - metres(180))

    result = _cluster([a, b, c])

    sizes = sorted(len(cl.members) for cl in result.clusters)
    assert sizes == [1, 2], f"expected a pair and a single, got {sizes}"
    assert result.review, "the blocked link should be surfaced for review"


def test_rejected_pair_is_never_merged():
    a = record("pge", "1")
    b = record("siteguide_au", "a", lat=-33.7 - metres(50))
    result = _cluster([a, b], rejected={frozenset({a.key, b.key})})
    assert len(result.clusters) == 2
    assert result.review == []


def test_review_band_pair_is_surfaced_not_merged():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a", lat=-33.7 - metres(180))])
    assert len(result.clusters) == 2
    assert len(result.review) == 1
    assert result.review[0].band is Band.REVIEW


def test_review_is_sorted_by_ascending_distance():
    recs = [
        record("pge", "1"),
        record("siteguide_au", "a", lat=-33.7 - metres(200)),
        record("dhv", "x", lat=-33.7 - metres(120)),
    ]
    result = _cluster(recs)
    distances = [p.distance_m for p in result.review]
    assert distances == sorted(distances)
