"""Parses Site Guide's free-text wind conditions into compass directions.

Site Guide has no structured orientation field - it publishes prose in
`conditions` like "E-NE", "SSW to SSE", "NW- WSW (best WNW)" or "North East".
That matters because the 135 Australian launches with no PGE counterpart have
no other possible source of wind data, and without it the app cannot compute
flyability for them at all.

Grammar, inferred from the 198 real values:
  - commas separate independent entries: "SE, NE, W"
  - a hyphen or "to" makes a range: "E-SE", "SSW to SSE"
  - ranges take the *shorter* arc between endpoints, which is how they are
    conventionally written ("NW-SW" means NW->W->SW, not the long way round)
  - three points chain as consecutive ranges: "SW-S-SE"
  - "All" means every direction
  - parentheticals are advisory ("best WNW") and are stripped
  - directions may be spelled out: "North East", "South to South East"

Output is on the app's 8-point compass, since that is what the sites table
stores. A 16-point token like SSE lies between two of them and yields both.
"""

from __future__ import annotations

import re

_POINTS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
    "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}
EIGHT_POINT = {"N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
               "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0}
_HALF_SECTOR = 22.5

_TOKEN = re.compile(r"\b(NNE|NNW|SSE|SSW|ENE|ESE|WSW|WNW|NE|NW|SE|SW|N|S|E|W)\b")
# "All", "Any" and "Various" all mean the site works in any direction.
_ANY_DIRECTION = re.compile(r"\b(ALL|ANY|VARIOUS)\b")
_SPELLED = [
    (re.compile(r"\bNORTH[\s-]*EAST\b"), "NE"),
    (re.compile(r"\bNORTH[\s-]*WEST\b"), "NW"),
    (re.compile(r"\bSOUTH[\s-]*EAST\b"), "SE"),
    (re.compile(r"\bSOUTH[\s-]*WEST\b"), "SW"),
    (re.compile(r"\bNORTH\b"), "N"),
    (re.compile(r"\bSOUTH\b"), "S"),
    (re.compile(r"\bEAST\b"), "E"),
    (re.compile(r"\bWEST\b"), "W"),
]


def _normalize(text: str) -> str:
    out = text.upper()
    out = re.sub(r"\([^)]*\)", " ", out)  # advisory parentheticals
    for pattern, token in _SPELLED:
        out = pattern.sub(token, out)
    out = re.sub(r"\bTO\b", "-", out)
    return out


def _arc_covers(start: float, end: float) -> set[str]:
    """The 8-point directions lying on the shorter arc from start to end."""
    forward = (end - start) % 360
    if forward <= 180:
        low, span = start, forward
    else:
        low, span = end, (start - end) % 360
    found = set()
    for name, angle in EIGHT_POINT.items():
        if ((angle - low) % 360) <= span + 1e-9:
            found.add(name)
    return found


def _near(angle: float) -> set[str]:
    """8-point directions within half a sector of a single bearing."""
    return {
        name
        for name, value in EIGHT_POINT.items()
        if min((value - angle) % 360, (angle - value) % 360) <= _HALF_SECTOR + 1e-9
    }


def parse_conditions(text: str | None) -> set[str]:
    """Compass directions a launch is flyable in. Empty if nothing parses."""
    if not text:
        return set()

    normalized = _normalize(text)
    if _ANY_DIRECTION.search(normalized):
        return set(EIGHT_POINT)

    directions: set[str] = set()
    for segment in normalized.split(","):
        tokens = _TOKEN.findall(segment)
        if not tokens:
            continue
        if len(tokens) == 1:
            directions |= _near(_POINTS[tokens[0]])
            continue
        for first, second in zip(tokens, tokens[1:]):
            directions |= _arc_covers(_POINTS[first], _POINTS[second])
    return directions
