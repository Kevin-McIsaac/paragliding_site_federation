"""Which country a cluster is in, and who is authoritative there.

Both of these were previously decided by accident. The country was the first
non-null among the members, so it depended on member order - and it is what
decides whose name and wind win, so an upstream reordering could silently swap
the winner. The order among two guides scoped to one country fell out of `sorted`
on the provider name.
"""

import logging

from src.clustering import Cluster
from src.ids import IdRegistry
from src.selection import select
from tests.conftest import record


def _select(*members):
    return select(Cluster(members=members), IdRegistry())


def test_agreeing_sources_keep_their_country():
    site = _select(record("pge", "1", country="AU"), record("ansg", "a", country="AU"))
    assert site.country == "AU"
    assert site.primary == "ansg"


def test_a_scoped_guide_settles_a_disagreement(caplog):
    # PGE placing an Australian launch in New Zealand used to be able to demote
    # the Australian guide, because the country it was ranked against came from
    # whichever member happened to be first.
    with caplog.at_level(logging.WARNING):
        site = _select(
            record("pge", "1", country="NZ", name="Wrong country"),
            record("ansg", "a", country="AU", name="Rabbit Hill"),
        )

    assert site.country == "AU"
    assert site.primary == "ansg", "the guide scoped to AU must still win in AU"
    assert site.name == "Rabbit Hill"
    assert "claims countries" in caplog.text, "a disagreement must be reported"


def test_the_winner_does_not_depend_on_member_order():
    forward = _select(
        record("pge", "1", country="NZ"), record("ansg", "a", country="AU")
    )
    reverse = _select(
        record("ansg", "a", country="AU"), record("pge", "1", country="NZ")
    )

    assert forward.primary == reverse.primary == "ansg"
    assert forward.country == reverse.country == "AU"


def test_two_guides_in_one_country_rank_by_declared_order(monkeypatch):
    # The outcome must be a decision. Alphabetically "aaa" beats "ansg", so if
    # this still fell out of sorted() the assertion below would fail.
    monkeypatch.setattr(
        "src.selection.NATIONAL_SCOPE", {"ansg": ["AU"], "aaa": ["AU"]}
    )

    site = _select(
        record("aaa", "x", name="Second guide", country="AU"),
        record("ansg", "a", name="First guide", country="AU"),
    )

    assert site.primary == "ansg"
    assert site.name == "First guide"


def test_a_guide_outside_its_scope_ranks_below_pge():
    site = _select(
        record("ansg", "a", name="Guide", country="FR"),
        record("pge", "1", name="PGE", country="FR"),
    )

    assert site.primary == "pge", "the Australian guide has no authority in France"
    assert site.name == "PGE"
