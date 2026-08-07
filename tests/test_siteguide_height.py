"""Site Guide's `height` is free text; every real value pairs feet with metres.

Cases taken verbatim from the live /api/Export payload.
"""

import pytest

from src.sources.siteguide_au import _parse_height


@pytest.mark.parametrize(
    "text,expected",
    [
        ("280'/85m asl, 250' agl", 85.0),  # ASL metres, not the AGL figure
        ("1100' / 335m asl, 550ft / 168m agl", 335.0),
        ("55m / 170ft", 55.0),  # metres first
        ("2,450ft / 750m ASL", 750.0),  # thousands separator
        ("660m asl/ 460m agl", 660.0),
        ("2,035ft, 620m", 620.0),
        ("300' / 90m", 90.0),
    ],
)
def test_parses_metres_from_real_values(text, expected):
    assert _parse_height(text) == expected


def test_falls_back_to_feet_when_no_metres_given():
    assert _parse_height("1000ft") == pytest.approx(304.8)


def test_missing_or_unparseable_height_is_none():
    assert _parse_height(None) is None
    assert _parse_height("") is None
    assert _parse_height("on a hill") is None


def test_numeric_input_passes_through():
    assert _parse_height(250) == 250.0
