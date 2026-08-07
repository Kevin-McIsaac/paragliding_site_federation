"""Wind-condition parsing, against values taken verbatim from the live export."""

import pytest

from src.wind import parse_conditions


@pytest.mark.parametrize(
    "text,expected",
    [
        ("E", {"E"}),
        ("E-SE", {"E", "SE"}),
        ("WSW-WNW", {"W"}),
        ("NW-SW", {"NW", "W", "SW"}),  # shorter arc, via W - not the long way
        ("SE-NE", {"SE", "E", "NE"}),
        ("SW-S-SE", {"SW", "S", "SE"}),  # three points chain as two ranges
        ("SSW to SSE", {"S"}),  # "to" is a range
        ("SE, NE, W", {"SE", "NE", "W"}),  # commas are independent entries
        ("SE?", {"SE"}),
        ("All", {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}),
        ("Any", {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}),
        ("Various", {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}),
        ("North East", {"NE"}),  # spelled out
        ("South to South East", {"S", "SE"}),
        ("NW- WSW (best WNW)", {"NW", "W"}),  # parenthetical advice ignored
        ("W-SSW, Thermic", {"W", "SW"}),  # unparseable words ignored
    ],
)
def test_parses_real_conditions(text, expected):
    assert parse_conditions(text) == expected


def test_sixteen_point_token_yields_both_neighbours():
    """SSE sits exactly between SE and S, so it means both."""
    assert parse_conditions("SSE") == {"SE", "S"}


@pytest.mark.parametrize("text", [None, "", "Thermic", "soarable over 10 knots"])
def test_unparseable_input_yields_nothing(text):
    assert parse_conditions(text) == set()


def test_long_reef_launches_stay_distinguishable():
    """The pair that motivated the old name-based compass gate: their own
    published conditions separate them without any name heuristic."""
    ne = parse_conditions("North East")
    se = parse_conditions("South to South East")
    assert not (ne & se)
