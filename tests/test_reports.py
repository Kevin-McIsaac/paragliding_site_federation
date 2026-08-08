"""The three markdown reports: near-misses, overrides, duplicates."""

import pytest

from src.reports import render_overrides
from tests.conftest import metres, record


def test_overrides_report_resolves_keys_to_names():
    """rejections.json holds opaque keys; the report is what makes it readable."""
    pge = record("pge", "1", name="Long Reef NE", url="https://www.paraglidingearth.com/?site=1")
    au = record("siteguide_au", "a", name="Long Reef SE", url="https://siteguide.org.au/sites/details/9")
    entries = [{"a": "pge:1", "b": "siteguide_au:a", "verdict": "never", "reason": "opposite aspects of one ridge"}]

    table = render_overrides(entries, [pge, au], set())

    assert "[Long Reef NE](https://www.paraglidingearth.com/?site=1)" in table
    assert "opposite aspects of one ridge" in table
    assert "| yes |" in table


def test_overrides_report_flags_a_key_that_no_longer_resolves():
    """A source can drop or renumber a site, leaving an entry suppressing
    nothing - that must be visible, not silently dropped."""
    entries = [{"a": "pge:999", "b": "siteguide_au:a", "verdict": "never", "reason": "gone"}]

    table = render_overrides(entries, [record("siteguide_au", "a")], set())

    assert "`pge:999`" in table
    assert "stale" in table


def test_overrides_report_when_empty():
    assert "**0** pairs forced apart" in render_overrides([], [], set())


def test_reason_containing_a_pipe_cannot_break_the_table():
    entries = [{"a": "pge:1", "b": "siteguide_au:a", "verdict": "never", "reason": "north | south"}]
    table = render_overrides(entries, [record("pge", "1"), record("siteguide_au", "a")], set())
    assert r"north \| south" in table


def test_intra_source_pairs_skip_launches_under_one_parent():
    """Two launches of one Site Guide site are deliberately distinct - "The
    Paps - South west" and "- South east" are 47m apart and both real."""
    from src.matcher import intra_source_pairs

    a = record("siteguide_au", "212-1", name="The Paps - South west", group_id="212")
    b = record("siteguide_au", "212-2", name="The Paps - South east",
               lat=-33.7 - metres(47), group_id="212")

    assert list(intra_source_pairs([a, b])) == []


def test_intra_source_pairs_report_a_genuine_same_source_duplicate():
    a = record("pge", "7596", name="Little Europe", group_id=None)
    b = record("pge", "10714", name="Lake St Clair", lat=-33.7 - metres(133), group_id=None)

    from src.matcher import intra_source_pairs

    found = list(intra_source_pairs([a, b]))

    assert len(found) == 1
    assert found[0][2] == pytest.approx(133, abs=1)


def test_duplicates_report_shows_wind_so_deliberate_pairs_are_obvious():
    """Opposite aspects are the clearest sign a close pair is intentional."""
    from src.reports import render_duplicates

    a = record("siteguide_au", "1", name="Tasman 3", wind={"E": 1, "NE": 1})
    b = record("siteguide_au", "2", name="Tasman 4", wind={"W": 1, "NW": 1})

    table = render_duplicates([(a, b, 35.0)])

    assert "| E,NE |" in table and "| NW,W |" in table


def test_keys_cell_is_copy_pasteable():
    """Constructing an override used to mean hunting two identifiers out of
    two datasets; one selection should now yield both."""
    from src.reports import keys_cell

    a = record("pge", "10714")
    b = record("siteguide_au", "109-238")

    assert keys_cell(a, b) == "`pge:10714 siteguide_au:109-238`"


def test_overrides_report_flags_a_forced_pair_that_did_not_apply():
    entries = [{"a": "pge:1", "b": "siteguide_au:a", "verdict": "always", "reason": "one site"}]
    recs = [record("pge", "1"), record("siteguide_au", "a")]

    assert "not applied" in render_overrides(entries, recs, set())
    assert "| yes |" in render_overrides(entries, recs, {frozenset({"pge:1", "siteguide_au:a"})})
