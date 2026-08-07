"""Country-sharded output and its idempotency guarantee."""

import json

from src.canonical_store import write_sites
from src.clustering import Cluster
from src.ids import IdRegistry
from src.selection import select
from tests.conftest import record


def _site(registry, provider="pge", id="1", **overrides):
    return select(Cluster(members=(record(provider, id, **overrides),)), registry)


def test_sites_are_sharded_by_country(tmp_path):
    registry = IdRegistry()
    sites = [_site(registry, id="1", country="AU"), _site(registry, id="2", country="FR")]

    write_sites(sites, tmp_path)

    assert (tmp_path / "au.json").exists()
    assert (tmp_path / "fr.json").exists()


def test_rerun_with_unchanged_input_writes_nothing(tmp_path):
    registry = IdRegistry()
    sites = [_site(registry, id="1")]
    write_sites(sites, tmp_path)
    mtime = (tmp_path / "au.json").stat().st_mtime_ns

    counts = write_sites([_site(IdRegistry(keys={"pge:1": "PSF-000001"}, next_id=2), id="1")], tmp_path)

    assert counts["written"] == 0
    assert counts["unchanged"] == 1
    assert (tmp_path / "au.json").stat().st_mtime_ns == mtime


def test_changed_site_rewrites_only_its_country(tmp_path):
    registry = IdRegistry()
    write_sites([_site(registry, id="1", country="AU"), _site(registry, id="2", country="FR")], tmp_path)
    fr_mtime = (tmp_path / "fr.json").stat().st_mtime_ns

    registry_two = IdRegistry(keys={"pge:1": "PSF-000001", "pge:2": "PSF-000002"}, next_id=3)
    counts = write_sites(
        [
            _site(registry_two, id="1", country="AU", name="Renamed"),
            _site(registry_two, id="2", country="FR"),
        ],
        tmp_path,
    )

    assert counts["written"] == 1
    assert (tmp_path / "fr.json").stat().st_mtime_ns == fr_mtime


def test_sites_are_sorted_by_id_within_a_shard(tmp_path):
    registry = IdRegistry()
    sites = [_site(registry, id=str(i)) for i in range(1, 6)]
    write_sites(list(reversed(sites)), tmp_path)

    payload = json.loads((tmp_path / "au.json").read_text())
    assert [s["id"] for s in payload] == sorted(s["id"] for s in payload)


def test_emptied_country_file_is_removed(tmp_path):
    registry = IdRegistry()
    write_sites([_site(registry, id="1", country="AU"), _site(registry, id="2", country="FR")], tmp_path)

    write_sites([_site(IdRegistry(keys={"pge:1": "PSF-000001"}, next_id=2), id="1", country="AU")], tmp_path)

    assert (tmp_path / "au.json").exists()
    assert not (tmp_path / "fr.json").exists()
