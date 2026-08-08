"""Human decisions that override the distance rule. The only file you edit.

Matching decides on distance alone, so this is the single escape hatch for the
pairs it gets wrong - in both directions:

    [{"a": "pge:21219", "b": "siteguide_au:129-34", "verdict": "never",
      "reason": "north-facing launch, distinct from the NE one"},
     {"a": "pge:18871", "b": "siteguide_au:125-3", "verdict": "always",
      "reason": "one site; PGE's pin is 387m off the real launch"}]

One entry per pair, because "never" and "always" are opposite answers to the
same question and a pair cannot be both. A single list makes that
contradiction impossible to express, which two files would not.

`never` is a filter. `always` is not its mirror image: a forced pair has to
bypass the distance, role and approximate-coordinate gates entirely, so it
seeds a cluster before merging starts rather than arriving as a scored pair.

Every report carries a copy-pasteable key pair, so adding an entry is a copy
and a word, not a hunt through two datasets for identifiers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

OVERRIDES_PATH = Path("overrides.json")
NEVER = "never"
ALWAYS = "always"
_VERDICTS = (NEVER, ALWAYS)


class OverrideError(ValueError):
    """Raised rather than guessing - a malformed entry silently ignored would
    look exactly like a decision that was never applied."""


@dataclass(frozen=True)
class Overrides:
    entries: list[dict] = field(default_factory=list)
    never: set[frozenset[str]] = field(default_factory=set)
    always: set[frozenset[str]] = field(default_factory=set)

    def verdict_for(self, keys: frozenset[str]) -> str | None:
        if keys in self.never:
            return NEVER
        if keys in self.always:
            return ALWAYS
        return None


def load(path: Path | None = None) -> Overrides:
    target = path or OVERRIDES_PATH
    if not target.exists():
        return Overrides()

    entries = json.loads(target.read_text())
    if not isinstance(entries, list):
        raise OverrideError(f"{target} must contain a JSON array")

    never: set[frozenset[str]] = set()
    always: set[frozenset[str]] = set()
    seen: set[frozenset[str]] = set()

    for index, entry in enumerate(entries):
        a, b = entry.get("a"), entry.get("b")
        if not a or not b:
            raise OverrideError(f"{target}[{index}]: needs both 'a' and 'b' source keys")
        verdict = entry.get("verdict")
        if verdict not in _VERDICTS:
            raise OverrideError(
                f"{target}[{index}]: verdict must be one of {_VERDICTS}, got {verdict!r}"
            )
        keys = frozenset({a, b})
        if keys in seen:
            raise OverrideError(f"{target}[{index}]: {a} / {b} appears more than once")
        seen.add(keys)
        (never if verdict == NEVER else always).add(keys)

    return Overrides(entries=entries, never=never, always=always)


def ensure_exists(path: Path | None = None) -> None:
    target = path or OVERRIDES_PATH
    if not target.exists():
        target.write_text("[]\n")
