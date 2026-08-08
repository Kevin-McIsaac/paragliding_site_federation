"""Orchestrates one run: fetch -> pair -> cluster -> select -> write."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import rejections, reports
from src.canonical_store import write_app_csv, write_sites
from src.clustering import cluster
from src.ids import IdRegistry
from src.matcher import pairs as build_pairs
from src.model import AUSTRALIA_BBOX, WORLD_BBOX
from src.run_summary import SourceStats, build_pr, check_health
from src.selection import select
from src.sources.pge import PgeSource
from src.sources.siteguide_au import SiteGuideAuSource

STATE_PATH = Path("state/last_run.json")
PR_OUTPUT_DIR = Path(".pr")


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"sources": {}, "siteguide_au": {"version_id": None}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def run(*, dry_run: bool, scope: str, force: bool) -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bbox = AUSTRALIA_BBOX if scope == "au" else WORLD_BBOX

    state = _load_state()
    previous = {n: e["record_count"] for n, e in state.get("sources", {}).items()}

    pge = PgeSource()
    siteguide = SiteGuideAuSource(
        last_version_id=None if force else state.get("siteguide_au", {}).get("version_id")
    )

    pge_records = pge.fetch(bbox)
    sg_records = siteguide.fetch(AUSTRALIA_BBOX)

    stats = [
        SourceStats("pge", len(pge_records), sum(1 for r in pge_records if r.wind)),
        SourceStats(
            "siteguide_au",
            len(sg_records) if not siteguide.skipped_unchanged else previous.get("siteguide_au", 0),
            sum(1 for r in sg_records if r.wind),
            skipped_unchanged=siteguide.skipped_unchanged,
        ),
    ]

    health = check_health(stats, previous)
    if not health.ok:
        print("Run health check failed - aborting before writing anything.", file=sys.stderr)
        for note in health.notes:
            print(f"  {note}", file=sys.stderr)
        return 1

    records = pge_records + sg_records
    rejection_entries = rejections.load_entries()
    result = cluster(records, list(build_pairs(records)), rejected=rejections.load())
    merged = sum(1 for c in result.clusters if len(c.members) > 1)
    no_wind = 0

    if dry_run:
        print(
            f"[dry-run] scope={scope} pge={len(pge_records)} siteguide_au={len(sg_records)} "
            f"clusters={len(result.clusters)} merged={merged} review={len(result.review)}"
        )
        return 0

    registry = IdRegistry.load()
    sites = [select(c, registry) for c in sorted(result.clusters, key=lambda c: sorted(c.keys)[0])]
    no_wind = sum(1 for s in sites if not s.wind)

    site_counts = write_sites(sites)
    csv_changed = write_app_csv(sites)
    merged_changed = reports.write_merged(result.clusters)
    review_changed = reports.write_review(result.review, merged)
    rejected_changed = reports.write_rejected(rejection_entries, records)
    rejections.ensure_exists()
    registry.save()

    title, body = build_pr(
        run_id=run_id,
        stats=stats,
        site_counts=site_counts,
        merged_clusters=merged,
        review=result.review,
        health=health,
        no_wind=no_wind,
    )

    has_changes = any((site_counts["written"] > 0, csv_changed, merged_changed,
                      review_changed, rejected_changed))
    PR_OUTPUT_DIR.mkdir(exist_ok=True)
    (PR_OUTPUT_DIR / "has_changes.txt").write_text("true" if has_changes else "false")
    (PR_OUTPUT_DIR / "title.txt").write_text(title)
    (PR_OUTPUT_DIR / "body.md").write_text(body)

    state["sources"] = {s.name: {"record_count": s.record_count} for s in stats}
    state.setdefault("siteguide_au", {})["version_id"] = siteguide.current_version_id
    _save_state(state)

    print(title)
    print(body)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scope", choices=("world", "au"), default="world")
    parser.add_argument("--force", action="store_true", help="Ignore the Site Guide version gate.")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, scope=args.scope, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
