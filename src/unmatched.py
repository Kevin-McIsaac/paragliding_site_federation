"""Writes the plain backlog of source sites with no viable PGE candidate at all.

A single stable path, not one file per run - these are worklist entries, not
assertions of truth, so there's nothing to diff-and-review per item the way a
proposed link has. Keeping one file (sorted deterministically) means a run
with no real change to the backlog doesn't touch this file at all, matching
the idempotency rule used everywhere else.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.model import SiteRecord

UNMATCHED_PATH = Path("unmatched/current.jsonl")


def write_unmatched(sites: list[SiteRecord]) -> bool:
    """Overwrite the worklist if it changed. Returns True if the file changed."""
    UNMATCHED_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"provider": s.provider, "id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon})
        for s in sorted(sites, key=lambda s: (s.provider, s.id))
    ]
    new_content = "\n".join(lines) + ("\n" if lines else "")
    old_content = UNMATCHED_PATH.read_text() if UNMATCHED_PATH.exists() else None
    if old_content == new_content:
        return False
    UNMATCHED_PATH.write_text(new_content)
    return True
