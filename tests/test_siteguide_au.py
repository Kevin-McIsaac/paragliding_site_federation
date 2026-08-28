"""Turning Site Guide's free-text `height` into a sea-level altitude.

The strings below are real export values (issue #8). The rule is by label,
not position: `asl`/`amsl` wins wherever it sits, an `agl`-only value is
refused outright - it is a height above the ground, which the catalogue has
no business publishing in an AMSL field - and unlabelled values keep the
first-metre-figure reading the other 176 sites rely on.
"""

import pytest

from src.sources.siteguide_au import _parse_height


@pytest.mark.parametrize(
    ("height", "expected"),
    [
        # The convention the old first-figure rule assumed - unchanged.
        ("280'/85m asl, 250' agl", 85.0),
        ("2,450ft / 750m ASL", 750.0),
        ("55m / 170ft", 55.0),
        # Group A: the `asl`/`amsl` figure is there but no longer first.
        ("3100' / 945m agl; 3540' / 1080m asl", 1080.0),
        ("1850' / 560m agl, 3182' / 970m amsl", 970.0),
        # Group B: only a height above the ground - publish nothing instead
        # of an AMSL that is off by the height of the hill.
        ("840ft / 255m agl", None),
        ("120m agl", None),
        ("300 ft agl", None),
        # A feet figure may be the labelled one.
        ("2400' amsl", 731.5),
        # Comma thousands never confused with a separator.
        ("1,080m asl", 1080.0),
        ("2,450ft / 750m asl", 750.0),
        # The label may ride on the feet of an ft/m pair; the metre figure of
        # the same piece is the same height, read rather than converted.
        ("950m / 3100' ASL, 350m / 1150' AGL", 950.0),
        ("300' asl, 90m asl", 90.0),
    ],
)
def test_labelled_heights_parse_by_label(height, expected):
    assert _parse_height(height) == expected


def test_a_number_stands_alone():
    assert _parse_height(436) == 436.0


def test_nothing_stated_is_nothing_published():
    assert _parse_height(None) is None
    assert _parse_height("") is None
    assert _parse_height("no figure here") is None


def test_unlabelled_feet_are_converted():
    assert _parse_height("2800 ft") == pytest.approx(853.4, abs=0.1)