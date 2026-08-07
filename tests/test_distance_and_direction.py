"""The distance plateau and the compass-direction gate.

Both were derived from measured behaviour on the real Australian sources
rather than chosen a priori - see the docstrings in matcher.py.
"""

import pytest

from src.matcher import _direction_conflict, score_pair
from tests.conftest import record


def _pair(distance_deg=0.0, **overrides):
    a = record("pge", "1")
    b = record("siteguide_au", "a", lat=-33.7 - distance_deg, **overrides)
    return score_pair(a, b)


def test_distance_carries_no_penalty_inside_the_plateau():
    """Coordinates tens of metres apart describe the same launch; the gap is
    GPS and data-entry error, not evidence against a match."""
    touching = _pair(0.0)
    eighty_metres = _pair(0.0007)

    assert eighty_metres.components.distance_score == touching.components.distance_score == 1.0


def test_identical_names_still_merge_at_a_few_hundred_metres():
    """The regression the plateau exists to fix: "Serpentine" ~ "Serpentine"
    at 245m scored 0.70 under the old decay and was sent to manual review."""
    pair = _pair(0.0022)  # ~245m
    assert pair.confidence >= 0.80


def test_distance_still_decays_beyond_the_plateau():
    near = _pair(0.0011)  # ~122m
    far = _pair(0.0055)  # ~610m
    assert far.components.distance_score < near.components.distance_score


def test_opposing_compass_directions_never_merge():
    """"Long Reef NE" and "Long Reef SE" are 200m apart with near-identical
    names - every other signal says merge, and they are different launches."""
    a = record("pge", "1", name="Long Reef NE")
    b = record("siteguide_au", "a", lat=-33.7018, name="Long Reef SE")
    assert score_pair(a, b) is None


@pytest.mark.parametrize(
    "left,right",
    [
        ("N.E Bonny Hills", "Bartletts Reserve - NE Bonnys"),  # "N.E" == "NE"
        ("S.E Bonny Hills", "Grants Headland - SE Bonnys"),
        ("NE Heaton", "NNE Heaton Lookout"),  # adjacent points, not opposed
        ("Bald Hill", "Bald Hill"),  # no direction tokens at all
        ("Mount Emu", "Emu 1"),
    ],
)
def test_compatible_or_absent_directions_do_not_block(left, right):
    assert not _direction_conflict(record("pge", "1", name=left), record("siteguide_au", "a", name=right))


def test_direction_gate_does_not_fire_on_one_sided_tokens():
    """Only one name carrying a direction says nothing about disagreement."""
    assert not _direction_conflict(record("pge", "1", name="Stanwell Park"), record("siteguide_au", "a", name="SE launch"))
