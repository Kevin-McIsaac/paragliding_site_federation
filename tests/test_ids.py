"""Canonical ids must be stable across runs - flight history references them.

A run boundary is a save + reload, not a second call on a live registry: the
claim tracking that detects cluster splits is per-run state. `next_run` below
is what actually happens in CI between weekly runs.
"""

from src.ids import IdRegistry


def next_run(registry, tmp_path):
    path = tmp_path / "id_registry.json"
    registry.save(path)
    return IdRegistry.load(path)


def test_new_cluster_gets_a_fresh_id():
    registry = IdRegistry()
    assert registry.assign(frozenset({"pge:1"})) == "PSF-000001"
    assert registry.assign(frozenset({"pge:2"})) == "PSF-000002"


def test_same_cluster_keeps_its_id_across_runs(tmp_path):
    registry = IdRegistry()
    first = registry.assign(frozenset({"pge:1", "ansg:a"}))

    second = next_run(registry, tmp_path).assign(frozenset({"pge:1", "ansg:a"}))

    assert first == second


def test_cluster_gaining_a_member_keeps_its_id(tmp_path):
    registry = IdRegistry()
    original = registry.assign(frozenset({"pge:1"}))

    grown = next_run(registry, tmp_path).assign(frozenset({"pge:1", "ansg:a"}))

    assert grown == original


def test_merged_clusters_inherit_the_lowest_id(tmp_path):
    registry = IdRegistry()
    first = registry.assign(frozenset({"pge:1"}))
    registry.assign(frozenset({"ansg:a"}))

    merged = next_run(registry, tmp_path).assign(frozenset({"pge:1", "ansg:a"}))

    assert merged == first  # oldest wins, so the outcome is order-independent


def test_reassigning_an_identical_cluster_is_idempotent():
    registry = IdRegistry()
    first = registry.assign(frozenset({"pge:1", "ansg:a"}))
    assert registry.assign(frozenset({"pge:1", "ansg:a"})) == first


def test_split_cluster_gives_each_half_a_distinct_id():
    """A cluster that splits must not hand the same id to both halves - that
    would put duplicate ids in the dataset and break the app's site lookup."""
    registry = IdRegistry(keys={"pge:1": "PSF-000001", "ansg:a": "PSF-000001"}, next_id=2)

    kept = registry.assign(frozenset({"pge:1"}))
    split_off = registry.assign(frozenset({"ansg:a"}))

    assert kept == "PSF-000001"  # first assigned keeps the anchor id
    assert split_off != kept
    assert split_off == "PSF-000002"


def test_ids_are_unique_within_a_run():
    registry = IdRegistry(
        keys={"pge:1": "PSF-000001", "pge:2": "PSF-000001", "pge:3": "PSF-000001"}, next_id=2
    )
    assigned = [registry.assign(frozenset({k})) for k in ("pge:1", "pge:2", "pge:3")]
    assert len(set(assigned)) == 3


def test_ids_are_never_reused():
    registry = IdRegistry()
    registry.assign(frozenset({"pge:1"}))
    registry.assign(frozenset({"pge:2"}))

    round_tripped = IdRegistry(keys={}, next_id=3)
    assert round_tripped.assign(frozenset({"pge:99"})) == "PSF-000003"


def test_registry_round_trips_through_disk(tmp_path):
    path = tmp_path / "id_registry.json"
    registry = IdRegistry()
    original = registry.assign(frozenset({"pge:1"}))
    registry.save(path)

    reloaded = IdRegistry.load(path)
    assert reloaded.assign(frozenset({"pge:1"})) == original
    assert reloaded.assign(frozenset({"pge:new"})) == "PSF-000002"
