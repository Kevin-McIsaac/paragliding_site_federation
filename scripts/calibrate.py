"""Measure whether MERGE_DISTANCE_M is right for a source before adding it.

The threshold is one number for the whole world, which is only defensible if
somebody checks it against each new guide's data. It was calibrated on Australia
- English names, good coordinates, one national source - and the Alps are far
denser, so "250 m worked there" is not evidence about anywhere else.

What to read:

  * the histogram. A cliff well inside the threshold means merges are decided by
    clearly-coincident coordinates. A flat run straddling it means the threshold
    is sitting in the middle of the evidence, which is where it does harm.
  * the sample of pairs either side of the threshold. This is the actual test:
    if the names just *past* it plainly describe one hill, the threshold is too
    tight for this region; if the names just *inside* it disagree, too loose.
  * the second-candidate rate. High means one source resolves launches the other
    lumps, so the nearest-first assignment is doing real work and the cluster
    guard matters more than the threshold does.

    python -m scripts.calibrate dhv de at ch

Compares a source's records against the launches already published for those
countries, so it answers "what would adding this guide do" rather than
re-deriving what the pipeline already agrees with itself about.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from src.matcher import MERGE_DISTANCE_M, REVIEW_DISTANCE_M, haversine_m
from src.sources import ADAPTERS

SITES_DIR = Path("sites")
_BANDS = ((0, 50), (50, 100), (100, 150), (150, 200), (200, 250),
          (250, 300), (300, 400), (400, 1000))


def _published(countries: list[str]) -> list[tuple[str, float, float]]:
    sites: list[tuple[str, float, float]] = []
    for country in countries:
        path = SITES_DIR / f"{country.lower()}.json"
        if not path.exists():
            print(f"  (no published shard for {country})", file=sys.stderr)
            continue
        sites += [(s["name"], s["lat"], s["lon"]) for s in json.loads(path.read_text())]
    return sites


def calibrate(source_name: str, countries: list[str]) -> int:
    adapter = next((a() for a in ADAPTERS if a.name == source_name), None)
    if adapter is None:
        known = ", ".join(sorted(a.name for a in ADAPTERS))
        print(f"Unknown source {source_name!r}. Known: {known}", file=sys.stderr)
        return 1

    records = [r for r in adapter.fetch(adapter.bbox) if r.role == "launch"]
    catalogue = _published(countries)
    if not records or not catalogue:
        print("Nothing to compare.", file=sys.stderr)
        return 1

    histogram: Counter[tuple[int, int]] = Counter()
    ambiguous = 0
    inside: list[tuple[float, str, str]] = []
    outside: list[tuple[float, str, str]] = []

    for r in records:
        ranked = sorted(
            ((haversine_m(r.lat, r.lon, c[1], c[2]), c[0]) for c in catalogue),
            key=lambda d: d[0],
        )[:2]
        distance, name = ranked[0]
        for low, high in _BANDS:
            if low <= distance < high:
                histogram[(low, high)] += 1
        if len(ranked) > 1 and ranked[1][0] < MERGE_DISTANCE_M:
            ambiguous += 1
        if MERGE_DISTANCE_M * 0.6 <= distance < MERGE_DISTANCE_M:
            inside.append((distance, r.name, name))
        elif MERGE_DISTANCE_M <= distance < REVIEW_DISTANCE_M:
            outside.append((distance, r.name, name))

    print(f"{source_name}: {len(records)} launches against "
          f"{len(catalogue)} published in {','.join(countries)}\n")
    for low, high in _BANDS:
        count = histogram[(low, high)]
        marker = "  <- merge threshold" if high == int(MERGE_DISTANCE_M) else ""
        print(f"  {low:4}-{high:4} m : {count:5} {'#' * min(count // 5, 60)}{marker}")
    beyond = len(records) - sum(histogram.values())
    print(f"  {'>1000':>9} m : {beyond:5}   (no counterpart - net-new launches)")
    print(f"\n  second candidate also within {MERGE_DISTANCE_M:.0f} m: "
          f"{ambiguous} ({ambiguous / len(records):.0%})")

    for label, rows in (("just inside", inside), ("just outside", outside)):
        print(f"\n  {label} the threshold - do these name one hill? ({len(rows)} pairs)")
        for distance, a, b in sorted(rows)[:12]:
            print(f"    {distance:4.0f} m  {a[:44]:44} | {b[:40]}")

    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    return calibrate(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
