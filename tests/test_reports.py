"""The four markdown reports: merged, near-misses, overrides, duplicates."""

import pytest

from src.clustering import Cluster
from src.reports import render_merged, render_overrides
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


def test_duplicates_are_split_into_a_table_per_source():
    """PGE's duplicates are mostly real; Site Guide's are mostly deliberate
    neighbours. One table invites applying one source's judgement to both."""
    from src.reports import render_duplicates

    pge = (record("pge", "1", name="Quinns"),
           record("pge", "2", name="Quinns Rocks", lat=-33.7 - metres(111)), 111.0)
    au = (record("siteguide_au", "a", name="Tasman 3"),
          record("siteguide_au", "b", name="Tasman 4", lat=-33.7 - metres(35)), 35.0)

    table = render_duplicates([pge, au])

    assert "## pge — 1 pairs" in table
    assert "## siteguide_au — 1 pairs" in table
    assert "**2** pairs, from 2 source(s)" in table


def test_override_cell_is_a_complete_pasteable_entry():
    """Strictly copy-paste: nothing to retype, so a mistyped key cannot
    silently override nothing."""
    from src.reports import override_cell

    cell = override_cell(record("pge", "10714"), record("siteguide_au", "109-238"), "always")

    assert cell == (
        '`{"a": "pge:10714", "b": "siteguide_au:109-238", '
        '"verdict": "always", "reason": ""}`'
    )


def test_override_cell_parses_as_a_valid_overrides_entry(tmp_path):
    """The pasted cell must actually load - proven by round-tripping it
    through the real loader rather than eyeballing the string."""
    import json

    from src import overrides
    from src.reports import override_cell

    cell = override_cell(record("pge", "1"), record("siteguide_au", "a"), "never")
    entry = json.loads(cell.strip("`"))

    path = tmp_path / "overrides.json"
    path.write_text(json.dumps([entry]))

    loaded = overrides.load(path)
    assert loaded.never == {frozenset({"pge:1", "siteguide_au:a"})}


def test_review_offers_always_and_merged_offers_never():
    """The verdict shown is the one that changes the outcome."""
    from src.clustering import ReviewItem, ReviewReason
    from src.matcher import pair_for
    from src.reports import render_merged, render_review

    pge, au = record("pge", "1"), record("siteguide_au", "a", lat=-33.7 - metres(300))
    review = render_review([ReviewItem(pair_for(pge, au), ReviewReason.BEYOND_THRESHOLD)])
    merged = render_merged([Cluster((record("pge", "1"), record("siteguide_au", "a")))])

    assert '"verdict": "always"' in review
    assert '"verdict": "never"' in merged


def test_overrides_report_flags_a_forced_pair_that_did_not_apply():
    entries = [{"a": "pge:1", "b": "siteguide_au:a", "verdict": "always", "reason": "one site"}]
    recs = [record("pge", "1"), record("siteguide_au", "a")]

    assert "not applied" in render_overrides(entries, recs, set())
    assert "| yes |" in render_overrides(entries, recs, {frozenset({"pge:1", "siteguide_au:a"})})


def test_merged_report_lists_both_source_names_and_the_distance():
    """The discarded name survives nowhere else: once Site Guide wins, PGE's
    name is gone from the CSV, the JSON and the app."""
    pge = record("pge", "1", name="80 Meter Dunes", url="https://www.paraglidingearth.com/?site=1")
    au = record("siteguide_au", "a", name="Wagga (80m dunes)",
                lat=-33.7 - metres(120), url="https://siteguide.org.au/sites/details/9")

    table = render_merged([Cluster((pge, au))])

    assert "[80 Meter Dunes](https://www.paraglidingearth.com/?site=1)" in table
    assert "[Wagga (80m dunes)](https://siteguide.org.au/sites/details/9)" in table
    assert "| 120 m |" in table
    # paste-ready, and offering the verdict that would undo the merge
    assert '`{"a": "pge:1", "b": "siteguide_au:a", "verdict": "never", "reason": ""}`' in table


def test_merged_report_ignores_single_source_clusters():
    table = render_merged([Cluster((record("pge", "1"),))])
    assert "**0** launches" in table


def test_merged_report_sorts_widest_gaps_last():
    """Distance is the thing to check, so the doubtful ones sit together."""
    close = Cluster((record("pge", "1", name="Close PGE"),
                     record("siteguide_au", "a", name="Close AU", lat=-33.7 - metres(30))))
    far = Cluster((record("pge", "2", name="Far PGE", lat=-34.0),
                   record("siteguide_au", "b", name="Far AU", lat=-34.0 - metres(240))))

    rows = [l for l in render_merged([far, close]).splitlines() if " m |" in l]

    assert "Close PGE" in rows[0] and "Far PGE" in rows[1]
