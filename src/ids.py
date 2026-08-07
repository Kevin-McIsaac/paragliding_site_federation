"""Stable canonical id allocation.

The app's flight history references site ids, so an id that churns between
runs is data loss rather than cosmetic churn. The registry maps every source
key to the canonical id it currently belongs to and is committed alongside
the dataset.

Rules:
  - a cluster whose source keys are all new gets a freshly allocated id
  - a cluster containing known keys inherits the *lowest* id among them, which
    makes the outcome independent of member ordering
  - when a cluster splits, whichever part holds that id keeps it and the rest
    are allocated new ids (a natural consequence of the rule above)
  - ids are never reused, even after a site disappears upstream
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path("state/id_registry.json")
_PREFIX = "PSF"


class IdRegistry:
    def __init__(self, keys: dict[str, str] | None = None, next_id: int = 1) -> None:
        self._keys: dict[str, str] = dict(keys or {})
        self._next_id = next_id
        self._claimed: dict[str, frozenset[str]] = {}

    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> "IdRegistry":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text())
        return cls(keys=payload.get("keys", {}), next_id=payload.get("next_id", 1))

    def save(self, path: Path = REGISTRY_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"next_id": self._next_id, "keys": dict(sorted(self._keys.items()))}
        path.write_text(json.dumps(payload, indent=2) + "\n")

    def assign(self, source_keys: frozenset[str]) -> str:
        known = sorted(self._keys[k] for k in source_keys if k in self._keys)

        # An inherited id already claimed by a *different* cluster this run
        # means the old cluster split. Only one part can keep the id - whichever
        # is assigned first, which the caller makes deterministic by processing
        # clusters in sorted order - and the rest are allocated fresh ones.
        # Re-assigning the identical cluster is idempotent.
        inherited = next(
            (i for i in known if self._claimed.get(i, source_keys) == source_keys), None
        )
        canonical_id = inherited or self._allocate()

        self._claimed[canonical_id] = source_keys
        for key in source_keys:
            self._keys[key] = canonical_id
        return canonical_id

    def _allocate(self) -> str:
        canonical_id = f"{_PREFIX}-{self._next_id:06d}"
        self._next_id += 1
        return canonical_id
