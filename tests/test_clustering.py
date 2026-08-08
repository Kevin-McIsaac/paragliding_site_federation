"""Clustering stays conservative and honours rejections."""

from src.clustering import cluster
from src.clustering import ReviewReason
from src.matcher import Band, pairs
from tests.conftest import metres, record


def _cluster(records, rejected=None):
    return cluster(records, list(pairs(records)), rejected=rejected)


def test_close_pair_forms_one_cluster():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a", lat=-33.7 - metres(120))])
    assert len(result.clusters) == 1
    assert len(result.clusters[0].members) == 2


def test_distant_records_stay_separate():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a", lat=-34.5)])
    assert len(result.clusters) == 2


def test_transitive_chain_does_not_fuse_three_records():
    """A-B 200m and B-C 200m, but A-C 400m: must not become one launch.

    Three providers, because same-source pairs are never compared and with
    only two the guard would appear to work for the wrong reason.
    """
    a = record("pge", "1", lat=-33.7)
    b = record("siteguide_au", "a", lat=-33.7 - metres(200))
    c = record("dhv", "x", lat=-33.7 - metres(400))

    result = _cluster([a, b, c])

    sizes = sorted(len(cl.members) for cl in result.clusters)
    assert sizes == [1, 2], f"expected a pair and a single, got {sizes}"
    assert result.review, "the blocked link should be surfaced for review"


def test_rejected_pair_is_never_merged():
    a = record("pge", "1")
    b = record("siteguide_au", "a", lat=-33.7 - metres(120))
    result = _cluster([a, b], rejected={frozenset({a.key, b.key})})
    assert len(result.clusters) == 2
    assert result.review == []


def test_near_miss_past_the_threshold_is_reported_not_merged():
    result = _cluster([record("pge", "1"), record("siteguide_au", "a", lat=-33.7 - metres(300))])
    assert len(result.clusters) == 2
    assert len(result.review) == 1
    assert result.review[0].pair.band is Band.REVIEW
    assert result.review[0].reason is ReviewReason.BEYOND_THRESHOLD


def test_pair_whose_sides_both_merged_elsewhere_is_not_reported():
    """Long Reef NE/SE: each matched its own counterpart, so the cross-pair
    is settled and listing it would invite impossible action."""
    pge_ne = record("pge", "1", lat=-33.7000)
    au_ne = record("siteguide_au", "a", lat=-33.7000 - metres(10))
    pge_se = record("pge", "2", lat=-33.7000 - metres(300))
    au_se = record("siteguide_au", "b", lat=-33.7000 - metres(310))

    result = _cluster([pge_ne, au_ne, pge_se, au_se])

    assert sorted(len(c.members) for c in result.clusters) == [2, 2]
    assert result.review == [], f"expected no report rows, got {len(result.review)}"


def test_review_is_sorted_by_ascending_distance():
    recs = [
        record("pge", "1"),
        record("siteguide_au", "a", lat=-33.7 - metres(200)),
        record("dhv", "x", lat=-33.7 - metres(120)),
    ]
    result = _cluster(recs)
    distances = [item.distance_m for item in result.review]
    assert distances == sorted(distances)


def test_a_closer_match_stealing_the_counterpart_is_labelled_as_such():
    """PGE holds two records for one place; Site Guide has one launch between
    them. The nearer PGE record wins it, and the other is left unmerged at a
    distance that would otherwise have merged - which is the visible symptom
    of a duplicate inside PGE."""
    near = record("pge", "1", name="Little Europe", lat=-33.7)
    au = record("siteguide_au", "a", lat=-33.7 - metres(33))
    far = record("pge", "2", name="Lake St Clair", lat=-33.7 - metres(133))

    result = _cluster([near, au, far])

    assert len(result.review) == 1
    item = result.review[0]
    assert item.pair.band is Band.MERGE, "close enough to merge, but blocked"
    assert item.reason is ReviewReason.COUNTERPART_MERGED
