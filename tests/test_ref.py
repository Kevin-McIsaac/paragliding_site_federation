"""The key the app stores against a flown site.

Emitted here rather than derived in the app, so one side decides. Two properties
matter and neither is obvious from reading `CanonicalSite.ref`:

  * it is *not* `primary`. `primary` says whose name and wind won - the local
    guide, in its own country. This says which id is the most durable handle, and
    for an Australian launch the two disagree on purpose;
  * it must match what the app's fallback would derive, or a fresh install and an
    upgraded one key the same launch differently.
"""

from src.clustering import Cluster
from src.ids import IdRegistry
from src.model import KEY_PRECEDENCE
from src.selection import select
from tests.conftest import record


def _select(*members):
    return select(Cluster(members=members), IdRegistry())


def test_prefers_pge_even_where_the_local_guide_owns_the_content():
    site = _select(
        record("ansg", "136-40", name="Manilla - Mt Borah - West", lat=-30.68),
        record("pge", "4632", name="Mt Borah", lat=-30.68),
    )

    assert site.primary == "ansg", "the local guide still supplies name and wind"
    assert site.ref == "pge:4632", "but the durable id keys it"


def test_uses_the_only_guide_that_has_one():
    assert _select(record("ansg", "136-21")).ref == "ansg:136-21"
    assert _select(record("pge", "4632")).ref == "pge:4632"


def test_is_deterministic_for_a_guide_with_no_ranking_yet():
    # A new source lands before anyone decides where it sits. Whatever it keys
    # on, two runs over the same cluster must agree, or every rebuild churns
    # the key and every device's link dangles.
    first = _select(record("zzz", "9"), record("aaa", "1")).ref
    second = _select(record("aaa", "1"), record("zzz", "9")).ref

    assert first == second == "aaa:1"


def test_ref_names_a_source_the_row_actually_lists():
    # The guard against ref drifting from `sources` - it is a derived property
    # precisely so this cannot happen, and this is what says so.
    site = _select(record("ansg", "136-40"), record("pge", "4632"))

    provider, source_id = site.ref.split(":", 1)
    assert site.sources[provider] == source_id


def test_precedence_is_ordered_most_durable_first():
    # Pinned because reordering it re-keys every launch the reorder touches, and
    # a re-key is a delete plus an insert on a device: the favourite goes with
    # the deleted row and every reference to the old key dangles permanently,
    # since that key is never emitted again. Nothing to do with a consumer's
    # copy of the list - there is no longer one. The app requires the emitted
    # `ref` and rejects a snapshot without it.
    assert KEY_PRECEDENCE == ("pge", "ansg", "dhv")
