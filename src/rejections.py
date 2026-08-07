"""Merges a human has declined, so the pipeline stops re-proposing them.

Without this a rejected match is regenerated identically on the next run and
gets re-reviewed forever. Edit rejections.json by hand to decline a merge:

    {"a": "pge:4632", "b": "siteguide_au:106-28",
     "reason": "distinct N- and S-facing launches on the same ridge"}
"""

from __future__ import annotations

import json
from pathlib import Path

REJECTIONS_PATH = Path("rejections.json")


def load(path: Path = REJECTIONS_PATH) -> set[frozenset[str]]:
    if not path.exists():
        return set()
    return {frozenset({entry["a"], entry["b"]}) for entry in json.loads(path.read_text())}


def ensure_exists(path: Path = REJECTIONS_PATH) -> None:
    if not path.exists():
        path.write_text("[]\n")
