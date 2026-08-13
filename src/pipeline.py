"""Orchestrates one run: fetch -> pair -> cluster -> select -> write."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import overrides, reports
from src.canonical_store import read_published, write_app_csv, write_sites
from src.clustering import cluster
from src.ids import IdRegistry
from src.matcher import intra_source_pairs
from src.matcher import pairs as build_pairs
from src.model import AUSTRALIA_BBOX, KEY_PRECEDENCE, WORLD_BBOX, intersect
from src.run_summary import (
    SourceStats,
    build_pr,
    check_health,
    check_output_health,
)
from src.selection import select
from src.sources import ADAPTERS

STATE_PATH = Path("state/last_run.json")
PR_OUTPUT_DIR = Path(".pr")


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"sources": {}, "ansg": {"version_id": None}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def run(*, dry_run: bool, scope: str) -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bbox = AUSTRALIA_BBOX if scope == "au" else WORLD_BBOX

    state = _load_state()
    previous = {n: e["record_count"] for n, e in state.get("sources", {}).items()}
    # The Australian guide was `siteguide_au` until it took its own name. Carried
    # over rather than dropped: check_health skips a source it has no previous
    # count for, so without this the drop gate would quietly not run for that
    # source on the first run after the rename.
    if "ansg" not in previous and "siteguide_au" in previous:
        previous["ansg"] = previous.pop("siteguide_au")

    adapters = [adapter() for adapter in ADAPTERS]

    # A guide with no entry in KEY_PRECEDENCE would be keyed by a `sorted()`
    # tie-break instead of a decision, and the app - which carries its own copy
    # of that list - would key the same launch differently. The app's comment
    # says this should be a hard failure here, because here is where the
    # decision can be made. Checked before fetching: no point spending a minute
    # on the network to fail on a constant.
    unranked = [a.name for a in adapters if a.name not in KEY_PRECEDENCE]
    if unranked:
        print(
            f"Adapters not ranked in KEY_PRECEDENCE: {', '.join(sorted(unranked))}. "
            f"Add them to src/model.py and to CatalogRef.providerPrecedence in the app.",
            file=sys.stderr,
        )
        return 1

    records = []
    stats = []
    for adapter in adapters:
        scoped = intersect(adapter.bbox, bbox)
        if scoped is None:
            continue
        fetched = adapter.fetch(scoped)
        records.extend(fetched)
        stats.append(
            SourceStats(adapter.name, len(fetched), sum(1 for r in fetched if r.wind))
        )

    health = check_health(stats, previous)
    if not health.ok:
        print("Run health check failed - aborting before writing anything.", file=sys.stderr)
        for note in health.notes:
            print(f"  {note}", file=sys.stderr)
        return 1

    decisions = overrides.load()
    result = cluster(records, list(build_pairs(records)),
                     rejected=decisions.never, forced=decisions.always)
    merged = sum(1 for c in result.clusters if len(c.members) > 1)
    no_wind = 0

    if dry_run:
        counts = " ".join(f"{s.name}={s.record_count}" for s in stats)
        print(
            f"[dry-run] scope={scope} {counts} "
            f"clusters={len(result.clusters)} merged={merged} review={len(result.review)}"
        )
        return 0

    registry = IdRegistry.load()
    sites = [select(c, registry) for c in sorted(result.clusters, key=lambda c: sorted(c.keys)[0])]
    no_wind = sum(1 for s in sites if not s.wind)

    output_health = check_output_health(sites, read_published())
    if not output_health.ok:
        print("Publish gates failed - aborting before writing anything.", file=sys.stderr)
        for note in output_health.notes:
            print(f"  {note}", file=sys.stderr)
        return 1
    for note in output_health.notes:
        print(f"[gates] {note}")

    site_counts = write_sites(sites)
    csv_changed = write_app_csv(sites)
    merged_changed = reports.write_merged(result.clusters)
    review_changed = reports.write_review(result.review, merged)
    overrides_changed = reports.write_overrides(decisions.entries, records, result.forced_applied)
    duplicate_pairs = list(intra_source_pairs(records))
    duplicates_changed = reports.write_duplicates(duplicate_pairs)
    overrides.ensure_exists()
    registry.save()

    title, body = build_pr(
        run_id=run_id,
        stats=stats,
        site_counts=site_counts,
        clusters=result.clusters,
        review=result.review,
        duplicates=duplicate_pairs,
        override_entries=decisions.entries,
        records=records,
        forced_applied=result.forced_applied,
        health=health,
        no_wind=no_wind,
    )

    has_changes = any((site_counts["written"] > 0, csv_changed, merged_changed,
                      review_changed, overrides_changed, duplicates_changed))
    PR_OUTPUT_DIR.mkdir(exist_ok=True)
    (PR_OUTPUT_DIR / "has_changes.txt").write_text("true" if has_changes else "false")
    (PR_OUTPUT_DIR / "title.txt").write_text(title)
    (PR_OUTPUT_DIR / "body.md").write_text(body)

    # Updated rather than replaced, so a scoped run that skipped a source out of
    # its area does not erase the count the drop gate compares against next week.
    # Names that are no longer adapters at all are dropped, though: assignment
    # used to clear them for free, and `update` alone would keep a renamed
    # provider's count in the file forever.
    known = {a.name for a in adapters}
    sources = state.setdefault("sources", {})
    sources.update({s.name: {"record_count": s.record_count} for s in stats})
    for retired in [name for name in sources if name not in known]:
        del sources[retired]
    for adapter in adapters:
        version_id = getattr(adapter, "current_version_id", None)
        if version_id is not None:
            state.setdefault(adapter.name, {})["version_id"] = version_id
    _save_state(state)

    print(title)
    print(body)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scope", choices=("world", "au"), default="world")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, scope=args.scope)


if __name__ == "__main__":
    raise SystemExit(main())
