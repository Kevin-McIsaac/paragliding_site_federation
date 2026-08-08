"""The three markdown reports: merged, near-misses, declined."""

from src.clustering import Cluster
from src.reports import render_merged, render_rejected
from tests.conftest import metres, record


def test_merged_report_lists_both_source_names_and_the_distance():
    pge = record("pge", "1", name="Rabbit Hill", url="https://www.paraglidingearth.com/?site=1")
    au = record("siteguide_au", "a", name="Yallingup - Rabbit Hill",
                lat=-33.7 - metres(120), url="https://siteguide.org.au/sites/details/9")

    table = render_merged([Cluster((pge, au))])

    assert "[Rabbit Hill](https://www.paraglidingearth.com/?site=1)" in table
    assert "[Yallingup - Rabbit Hill](https://siteguide.org.au/sites/details/9)" in table
    assert "| 120 m |" in table
    assert "**1** launches backed by more than one source" in table


def test_merged_report_ignores_single_source_clusters():
    table = render_merged([Cluster((record("pge", "1"),))])
    assert "**0** launches" in table
    assert "| _none_ |" in table


def test_merged_report_is_sorted_by_distance():
    close = Cluster((record("pge", "1", name="Close PGE"),
                     record("siteguide_au", "a", name="Close AU", lat=-33.7 - metres(30))))
    far = Cluster((record("pge", "2", name="Far PGE", lat=-34.0),
                   record("siteguide_au", "b", name="Far AU", lat=-34.0 - metres(200))))

    rows = [l for l in render_merged([far, close]).splitlines() if " m |" in l]

    assert "Close PGE" in rows[0] and "Far PGE" in rows[1]


def test_rejected_report_resolves_keys_to_names():
    """rejections.json holds opaque keys; the report is what makes it readable."""
    pge = record("pge", "1", name="Long Reef NE", url="https://www.paraglidingearth.com/?site=1")
    au = record("siteguide_au", "a", name="Long Reef SE", url="https://siteguide.org.au/sites/details/9")
    entries = [{"a": "pge:1", "b": "siteguide_au:a", "reason": "opposite aspects of one ridge"}]

    table = render_rejected(entries, [pge, au])

    assert "[Long Reef NE](https://www.paraglidingearth.com/?site=1)" in table
    assert "opposite aspects of one ridge" in table
    assert "| yes |" in table


def test_rejected_report_flags_a_key_that_no_longer_resolves():
    """A source can drop or renumber a site, leaving an entry suppressing
    nothing - that must be visible, not silently dropped."""
    entries = [{"a": "pge:999", "b": "siteguide_au:a", "reason": "gone"}]

    table = render_rejected(entries, [record("siteguide_au", "a")])

    assert "`pge:999`" in table
    assert "stale" in table


def test_rejected_report_when_empty():
    assert "**0** pairs will never be merged" in render_rejected([], [])


def test_reason_containing_a_pipe_cannot_break_the_table():
    entries = [{"a": "pge:1", "b": "siteguide_au:a", "reason": "north | south"}]
    table = render_rejected(entries, [record("pge", "1"), record("siteguide_au", "a")])
    assert r"north \| south" in table
