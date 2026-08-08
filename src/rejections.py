"""Pairs a human has declined, so the pipeline stops merging them.

Hand-edited, and the only decision file in the project. Add an entry to stop a
pair being merged:

    [{"a": "pge:4632", "b": "siteguide_au:106-28",
      "reason": "distinct N- and S-facing launches on the same ridge"}]

The keys are opaque on their own, so each run renders REJECTED.md with the
site names and links resolved - that is the readable view of this file.
"""

from __future__ import annotations

import json
from pathlib import Path

REJECTIONS_PATH = Path("rejections.json")


def load_entries(path: Path | None = None) -> list[dict]:
    target = path or REJECTIONS_PATH
    if not target.exists():
        return []
    return json.loads(target.read_text())


def load(path: Path | None = None) -> set[frozenset[str]]:
    return {frozenset({e["a"], e["b"]}) for e in load_entries(path)}


def ensure_exists(path: Path | None = None) -> None:
    target = path or REJECTIONS_PATH
    if not target.exists():
        target.write_text("[]\n")
