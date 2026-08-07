"""Pairs a human should look at: near-misses and transitive-only links.

These are not assertions - they are two records close enough to be suspicious
without clearing the bar to merge. Written as one deterministically-sorted
file rather than one file per pair, since there is nothing to decide per item
until someone acts on it (acting on it means adding to rejections.json, or
letting a future run merge it once the sources improve).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.matcher import ScoredPair

REVIEW_PATH = Path("review.json")


def write_review(pairs: list[ScoredPair], path: Path = REVIEW_PATH) -> bool:
    payload = [
        {
            "a": {"key": p.a.key, "name": p.a.name},
            "b": {"key": p.b.key, "name": p.b.name},
            "band": p.band.value,
            "confidence": p.confidence,
            "components": {
                "distance_m": p.components.distance_m,
                "distance_score": p.components.distance_score,
                "orientation_score": p.components.orientation_score,
                "name_score": p.components.name_score,
                "altitude_score": p.components.altitude_score,
            },
        }
        for p in sorted(pairs, key=lambda p: (-p.confidence, sorted(p.keys)[0]))
    ]
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True
