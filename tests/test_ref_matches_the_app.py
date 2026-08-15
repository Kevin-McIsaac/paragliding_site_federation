"""`ref` names a guide that actually describes the row.

This file used to reimplement the app's `CatalogRef.fromSource` in Python and
assert the emitted `ref` equalled it, because the app derived its own key from
`source` whenever a snapshot had no `ref` column. Two independent statements of
one rule, asserted equal.

The app no longer has a second statement: it requires the `ref` column and
rejects a snapshot without one, so a launch cannot be keyed `pge:` on a fresh
install and `ansg:` on an upgraded one. There is nothing left to mirror.

What replaces it is the property the app now depends on instead. It stores `ref`
as the key and builds one guide tab per token in `source`, so a `ref` naming a
provider absent from `source` would key a launch to a guide the page never
shows, and the tab would find no id to link out with. That cannot happen while
`ref` is derived from `sources` - which is the kind of "cannot happen" worth
sweeping the real output for.
"""

import json
import pathlib

SITES = pathlib.Path(__file__).resolve().parents[1] / "sites"


def _tokens(sources: dict[str, str]) -> set[str]:
    return {f"{provider}:{site_id}" for provider, site_id in sources.items()}


def test_a_freshly_selected_ref_is_one_of_its_own_sources():
    """The case this could plausibly break on: a launch both guides describe,
    where the local guide owns the content but PGE owns the key."""
    from src.clustering import Cluster
    from src.ids import IdRegistry
    from src.selection import select
    from tests.conftest import record

    clusters = [
        [record("pge", "4632", country="AU"), record("ansg", "136-40", country="AU")],
        [record("ansg", "136-21", country="AU")],
        [record("pge", "10001", country="BR")],
    ]
    for members in clusters:
        site = select(Cluster(members=members), IdRegistry())
        assert site.ref in _tokens(site.sources), site.sources


def test_every_published_ref_is_one_of_its_own_sources():
    checked = 0
    orphaned = []
    for path in sorted(SITES.glob("*.json")):
        for site in json.loads(path.read_text()):
            if "ref" not in site:
                continue
            checked += 1
            if site["ref"] not in _tokens(site["sources"]):
                orphaned.append(f"{path.name}: {site['id']} ref={site['ref']}")

    # Announced rather than passing quietly. A sweep over nothing that reports
    # success is worse than no sweep - it reads as coverage.
    if checked == 0:
        import pytest

        pytest.skip("no published site carries a ref yet; regenerate to cover this")

    assert orphaned == [], (
        f"{len(orphaned)} of {checked} refs name no contributing guide"
    )
