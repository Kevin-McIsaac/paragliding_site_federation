"""The DEM fill: which published altitudes it may touch, and which it must not.

`select()` already falls back to another member's altitude; the fill only ever
answers for rows left with nothing, and only where Site Guide is the source
that would otherwise have spoken - the other guides' absent altitudes are
their curation. The lookup itself is faked here; `test_elevation.py` covers it.
"""

import pytest

from src.clustering import Cluster
from src.ids import IdRegistry
from src.pipeline import _fill_ansg_altitudes
from src.selection import select
from tests.conftest import record


def _site(*members):
    return select(Cluster(members=members), IdRegistry())


def _stub(monkeypatch, resolved):
    monkeypatch.setattr(
        "src.elevation.amsl_for_coordinates", lambda coords: resolved
    )


def test_an_ansg_launch_with_no_altitude_takes_the_dem(monkeypatch):
    site = _site(record("ansg", "a", altitude=None))
    _stub(monkeypatch, {(site.lat, site.lon): 311.0})

    site = _fill_ansg_altitudes([site])[0]

    assert site.altitude == 311.0


def test_a_pge_figure_survives_the_fill(monkeypatch):
    # Mount Bakewell's case: the guide only knows a height above the ground,
    # and PGE's takeoff altitude is the better answer.
    site = _site(record("ansg", "a", altitude=None), record("pge", "1", altitude=436.0))
    _stub(monkeypatch, {(site.lat, site.lon): 311.0})

    site = _fill_ansg_altitudes([site])[0]

    assert site.altitude == 436.0


def test_the_guides_own_figure_beats_the_dem(monkeypatch):
    site = _site(record("ansg", "a", altitude=1080.0))
    _stub(monkeypatch, {(site.lat, site.lon): 311.0})

    site = _fill_ansg_altitudes([site])[0]

    assert site.altitude == 1080.0


def test_other_guides_absent_altitudes_are_not_filled(monkeypatch):
    site = _site(record("dhv", "x", altitude=None, country="DE"))
    _stub(monkeypatch, {(site.lat, site.lon): 311.0})

    site = _fill_ansg_altitudes([site])[0]

    assert site.altitude is None


def test_a_landing_is_left_for_its_own_decision(monkeypatch):
    # A landing's altitude feeds the app's launch-minus-landing drop; giving
    # it one here would surface that feature unreviewed. Landings stay bare.
    site = _site(record("ansg", "a", role="landing", altitude=None))
    _stub(monkeypatch, {(site.lat, site.lon): 311.0})

    site = _fill_ansg_altitudes([site])[0]

    assert site.altitude is None


def test_an_unreachable_api_leaves_the_altitude_absent(monkeypatch):
    site = _site(record("ansg", "a", altitude=None))
    _stub(monkeypatch, {})

    site = _fill_ansg_altitudes([site])[0]

    assert site.altitude is None