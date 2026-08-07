"""Unit tests for the gates, scoring components, and band assignment."""

from src.matcher import Band, match
from src.model import SiteRecord


def _pge(**overrides):
    defaults = dict(
        provider="pge",
        id="pge-1",
        name="Bald Hill",
        role="launch",
        lat=-33.7,
        lon=151.3,
        altitude=200.0,
        orientation=frozenset({"N", "NE"}),
        country="AU",
    )
    return SiteRecord(**{**defaults, **overrides})


def _other(**overrides):
    defaults = dict(
        provider="siteguide_au",
        id="sg-1",
        name="Bald Hill",
        role="launch",
        lat=-33.7,
        lon=151.3,
        altitude=200.0,
        orientation=frozenset({"N", "NE"}),
        country="AU",
    )
    return SiteRecord(**{**defaults, **overrides})


def test_clean_match_auto_links():
    result = match([_pge()], [_other()])
    assert len(result.linked) == 1
    assert result.linked[0].band is Band.AUTO_LINKED
    assert result.linked[0].confidence > 0.95
    assert result.unmatched == []


def test_role_mismatch_is_gated_out():
    result = match([_pge(role="launch")], [_other(role="landing")])
    assert result.linked == []
    assert result.candidates == []
    assert len(result.unmatched) == 1


def test_distance_beyond_candidate_radius_is_gated_out():
    far = _other(lat=-33.71)  # ~1.1km away, well past the 750m gate
    result = match([_pge()], [far])
    assert result.linked == []
    assert result.candidates == []
    assert len(result.unmatched) == 1


def test_borderline_distance_is_not_auto_linked():
    close_but_not_exact = _other(lat=-33.704, lon=151.3)  # ~445m away
    result = match([_pge()], [close_but_not_exact])
    bands = [m.band for m in result.linked + result.candidates]
    assert Band.AUTO_LINKED not in bands


def test_contradictory_orientation_lowers_confidence():
    mismatched = _other(orientation=frozenset({"S", "SW"}))  # opposite of pge's N/NE
    matched = _other(orientation=frozenset({"N", "NE"}))

    mismatched_result = match([_pge()], [mismatched])
    matched_result = match([_pge()], [matched])

    mismatched_score = (mismatched_result.linked + mismatched_result.candidates)[0].confidence
    matched_score = (matched_result.linked + matched_result.candidates)[0].confidence
    assert mismatched_score < matched_score


def test_explicit_reference_short_circuits_to_confirmed():
    pge = _pge(raw={"description": "See siteguide sg-1 for details"})
    other = _other(id="sg-1", role="landing")  # role mismatch would normally gate this out

    result = match([pge], [other])

    assert len(result.linked) == 1
    assert result.linked[0].provenance == "explicit_reference"
    assert result.linked[0].confidence == 1.0


def test_one_to_one_assignment_resolves_conflicts():
    exact = _pge(id="pge-a")
    nearby = _pge(id="pge-b", lat=-33.7005)  # slightly further, so it should lose
    other = _other()

    result = match([exact, nearby], [other])

    assert len(result.linked) == 1
    assert result.linked[0].pge_site.id == "pge-a"
