"""Gates, renormalized scoring, bands, and the spatial index."""

from src.matcher import Band, score_pair, scored_pairs
from tests.conftest import record


def test_identical_records_auto_link():
    pair = score_pair(record("pge", "1"), record("siteguide_au", "a"))
    assert pair is not None
    assert pair.band is Band.AUTO_LINKED
    assert pair.confidence > 0.95


def test_same_provider_is_never_compared():
    """Two launches from one source are a deliberate distinction, not a duplicate."""
    assert score_pair(record("siteguide_au", "a"), record("siteguide_au", "b")) is None


def test_role_mismatch_is_gated_out():
    assert score_pair(record("pge", "1", role="launch"), record("siteguide_au", "a", role="landing")) is None


def test_distance_beyond_gate_is_excluded():
    far = record("siteguide_au", "a", lat=-33.71)  # ~1.1km
    assert score_pair(record("pge", "1"), far) is None


def test_missing_signals_are_renormalized_not_penalized():
    """The v1 bug: a source with no wind/altitude data capped perfect matches
    near 0.82 because 0.35 of the weight sat at a neutral 0.5."""
    sparse = record("siteguide_au", "a", orientation=frozenset(), altitude=None)
    pair = score_pair(record("pge", "1"), sparse)

    assert pair.components.orientation_score is None
    assert pair.components.altitude_score is None
    assert pair.confidence > 0.95
    assert pair.band is Band.AUTO_LINKED


def test_contradictory_orientation_lowers_confidence():
    opposed = score_pair(record("pge", "1"), record("siteguide_au", "a", orientation=frozenset({"S", "SW"})))
    agreed = score_pair(record("pge", "1"), record("siteguide_au", "a"))
    assert opposed.confidence < agreed.confidence


def test_explicit_reference_outranks_gates():
    pge = record("pge", "1", raw={"siteguide_au_site_id": "a"})
    other = record("siteguide_au", "a", role="landing")  # would normally be gated out

    pair = score_pair(pge, other)

    assert pair.provenance == "explicit_reference"
    assert pair.confidence == 1.0


def test_spatial_index_finds_neighbours_across_cell_boundaries():
    a = record("pge", "1", lat=-33.70999, lon=151.3)
    b = record("siteguide_au", "a", lat=-33.71001, lon=151.3)  # different lat cell, ~2m apart

    pairs = list(scored_pairs([a, b]))

    assert len(pairs) == 1
    assert pairs[0].confidence > 0.95


def test_spatial_index_yields_each_pair_once():
    records = [record("pge", "1"), record("siteguide_au", "a"), record("siteguide_au", "b", lat=-33.7001)]
    pairs = list(scored_pairs(records))
    assert len({p.keys for p in pairs}) == len(pairs)
