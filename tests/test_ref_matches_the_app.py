"""The emitted `ref` must equal what the app's fallback would derive.

The app keys on the `ref` column when a snapshot has one and falls back to its own
`CatalogRef.fromSource` when it does not - an older bundled asset, or a snapshot
published before the column existed. Both paths have to agree, or the same launch
is keyed `pge:` on a fresh install and `ansg:` on an upgraded one.

This reimplements the app's rule deliberately, rather than importing it: it is
Dart, in another repository. Two independent statements of one rule that are
asserted equal is the point - if either side is edited alone, this fails.
"""

import json
import pathlib

SITES = pathlib.Path(__file__).resolve().parents[1] / "sites"

# lib/utils/catalog_ref.dart: CatalogRef.providerPrecedence, then tokens.first.
APP_PRECEDENCE = ("pge", "ansg", "dhv")


def app_ref(source_tokens: dict[str, str]) -> str:
    tokens = [f"{p}:{i}" for p, i in sorted(source_tokens.items())]
    for provider in APP_PRECEDENCE:
        for token in tokens:
            if token.split(":", 1)[0] == provider:
                return token
    return tokens[0]


def test_freshly_selected_sites_agree_with_the_apps_derivation():
    """Meaningful today, unlike the sweep below - it selects rather than reading.

    Covers the case the two rules could plausibly differ on: a launch both guides
    describe, where the local guide owns the content but PGE owns the key.
    """
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
        assert site.ref == app_ref(site.sources), site.sources


def test_every_published_site_agrees_with_the_apps_derivation():
    checked = disagreed = 0
    for path in sorted(SITES.glob("*.json")):
        for site in json.loads(path.read_text()):
            if "ref" not in site:
                continue
            checked += 1
            if site["ref"] != app_ref(site["sources"]):
                print(f"{path.name}: {site['id']} ref={site['ref']} "
                      f"app={app_ref(site['sources'])}")
                disagreed += 1

    # Announced rather than passing quietly. The committed output predates the
    # column until the pipeline next runs, and a sweep over nothing that reports
    # success is worse than no sweep - it reads as coverage.
    if checked == 0:
        import pytest

        pytest.skip("no published site carries a ref yet; regenerate to cover this")

    assert disagreed == 0, f"{disagreed} of {checked} refs disagree with the app"
