"""Reads and writes the one-file-per-link dataset with tombstone + idempotency rules."""

from __future__ import annotations

import json
from pathlib import Path

from src.matcher import Band, Match

LINKS_DIR = Path("links")
CANDIDATES_DIR = LINKS_DIR / "candidates"

_STATUS_BY_BAND = {
    Band.AUTO_LINKED: "auto_linked",
    Band.FLAGGED: "auto_linked_flagged",
    Band.CANDIDATE: "candidate",
}


def _path_for(m: Match) -> Path:
    filename = f"{m.pge_site.id}__{m.source_site.provider}-{m.source_site.id}.json"
    directory = CANDIDATES_DIR if m.band is Band.CANDIDATE else LINKS_DIR
    return directory / filename


def _record(m: Match, last_changed_run: str) -> dict:
    return {
        "pge_site": {"id": m.pge_site.id, "name": m.pge_site.name, "role": m.pge_site.role},
        "source": {
            "provider": m.source_site.provider,
            "id": m.source_site.id,
            "name": m.source_site.name,
            "role": m.source_site.role,
        },
        "match": {
            "status": _STATUS_BY_BAND[m.band],
            "confidence": round(m.confidence, 3),
            "provenance": m.provenance,
            "components": {
                "distance_m": m.components.distance_m,
                "distance_score": m.components.distance_score,
                "orientation_score": m.components.orientation_score,
                "name_score": m.components.name_score,
                "altitude_score": m.components.altitude_score,
            },
        },
        "last_changed_run": last_changed_run,
    }


def _without_timestamp(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "last_changed_run"}


def write_matches(matches: list[Match], run_id: str) -> dict[str, int]:
    """Write one file per match, skipping anything already tombstoned rejected.

    Returns counts for the run summary: added / updated / unchanged / skipped_rejected.
    """
    counts = {"added": 0, "updated": 0, "unchanged": 0, "skipped_rejected": 0}

    for m in matches:
        path = _path_for(m)
        existing = _read(path)

        if existing is not None and existing.get("match", {}).get("status") == "rejected":
            counts["skipped_rejected"] += 1
            continue

        new_record = _record(m, run_id)

        if existing is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write(path, new_record)
            counts["added"] += 1
        elif _without_timestamp(existing) != _without_timestamp(new_record):
            _write(path, new_record)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1

    return counts


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2) + "\n")
