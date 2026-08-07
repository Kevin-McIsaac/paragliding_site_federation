"""Unit tests for idempotent file writing and rejection tombstones."""

import json

from src import links_store
from src.matcher import Band, Match, MatchComponents
from src.model import SiteRecord


def _match(**overrides):
    pge = SiteRecord(provider="pge", id="pge-1", name="Bald Hill", role="launch", lat=-33.7, lon=151.3)
    other = SiteRecord(provider="siteguide_au", id="sg-1", name="Bald Hill", role="launch", lat=-33.7, lon=151.3)
    components = MatchComponents(
        distance_m=0.0, distance_score=1.0, orientation_score=0.5, name_score=1.0, altitude_score=0.5
    )
    defaults = dict(pge_site=pge, source_site=other, confidence=0.9, band=Band.AUTO_LINKED, components=components)
    return Match(**{**defaults, **overrides})


def _use_tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(links_store, "LINKS_DIR", tmp_path / "links")
    monkeypatch.setattr(links_store, "CANDIDATES_DIR", tmp_path / "links" / "candidates")


def test_new_match_is_added(tmp_path, monkeypatch):
    _use_tmp_dirs(tmp_path, monkeypatch)

    counts = links_store.write_matches([_match()], run_id="2026-08-10")

    assert counts == {"added": 1, "updated": 0, "unchanged": 0, "skipped_rejected": 0}
    assert len(list((tmp_path / "links").glob("*.json"))) == 1


def test_rerun_with_unchanged_input_is_a_noop(tmp_path, monkeypatch):
    _use_tmp_dirs(tmp_path, monkeypatch)

    links_store.write_matches([_match()], run_id="2026-08-10")
    path = next((tmp_path / "links").glob("*.json"))
    first_write_time = path.stat().st_mtime_ns

    counts = links_store.write_matches([_match()], run_id="2026-08-17")

    assert counts == {"added": 0, "updated": 0, "unchanged": 1, "skipped_rejected": 0}
    assert path.stat().st_mtime_ns == first_write_time


def test_changed_score_is_rewritten_with_new_timestamp(tmp_path, monkeypatch):
    _use_tmp_dirs(tmp_path, monkeypatch)

    links_store.write_matches([_match(confidence=0.9)], run_id="2026-08-10")
    counts = links_store.write_matches([_match(confidence=0.82)], run_id="2026-08-17")

    assert counts == {"added": 0, "updated": 1, "unchanged": 0, "skipped_rejected": 0}
    path = next((tmp_path / "links").glob("*.json"))
    record = json.loads(path.read_text())
    assert record["match"]["confidence"] == 0.82
    assert record["last_changed_run"] == "2026-08-17"


def test_rejected_tombstone_is_not_overwritten(tmp_path, monkeypatch):
    _use_tmp_dirs(tmp_path, monkeypatch)

    links_store.write_matches([_match()], run_id="2026-08-10")
    path = next((tmp_path / "links").glob("*.json"))
    record = json.loads(path.read_text())
    record["match"]["status"] = "rejected"
    record["match"]["rejected_reason"] = "distinct launches on the same ridge"
    path.write_text(json.dumps(record))

    counts = links_store.write_matches([_match()], run_id="2026-08-17")

    assert counts == {"added": 0, "updated": 0, "unchanged": 0, "skipped_rejected": 1}
    assert json.loads(path.read_text())["match"]["status"] == "rejected"


def test_candidate_band_is_written_to_candidates_subdir(tmp_path, monkeypatch):
    _use_tmp_dirs(tmp_path, monkeypatch)

    links_store.write_matches([_match(band=Band.CANDIDATE, confidence=0.4)], run_id="2026-08-10")

    assert list((tmp_path / "links").glob("*.json")) == []
    assert len(list((tmp_path / "links" / "candidates").glob("*.json"))) == 1
