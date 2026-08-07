"""Orchestrates one federation run: fetch -> match -> write -> summarize.

`python -m src.pipeline --dry-run` fetches and matches against the real APIs
but writes nothing - the intended first step before ever wiring up CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.links_store import write_matches
from src.matcher import match
from src.model import AUSTRALIA_BBOX
from src.run_summary import SourceStats, build_pr, check_health
from src.sources.pge import PgeSource
from src.sources.siteguide_au import SiteGuideAuSource
from src.unmatched import write_unmatched

STATE_PATH = Path("state/last_run.json")
PR_OUTPUT_DIR = Path(".pr")


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"sources": {}, "siteguide_au": {"version_id": None}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def run(*, dry_run: bool) -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    state = _load_state()
    previous_counts = {name: entry["record_count"] for name, entry in state["sources"].items()}

    pge = PgeSource()
    siteguide = SiteGuideAuSource(last_version_id=state["siteguide_au"].get("version_id"))

    pge_sites = pge.fetch(AUSTRALIA_BBOX)
    other_sites = siteguide.fetch(AUSTRALIA_BBOX)

    stats = [
        SourceStats(name="pge", record_count=len(pge_sites)),
        SourceStats(
            name="siteguide_au",
            record_count=(
                len(other_sites) if not siteguide.skipped_unchanged else previous_counts.get("siteguide_au", 0)
            ),
            skipped_unchanged=siteguide.skipped_unchanged,
        ),
    ]

    health = check_health(stats, previous_counts)
    if not health.ok:
        print("Run health check failed - aborting before writing anything.", file=sys.stderr)
        for note in health.notes:
            print(f"  {note}", file=sys.stderr)
        return 1

    result = match(pge_sites, other_sites)

    if dry_run:
        print(
            f"[dry-run] pge={len(pge_sites)} siteguide_au={len(other_sites)} "
            f"linked={len(result.linked)} candidates={len(result.candidates)} "
            f"unmatched={len(result.unmatched)}"
        )
        return 0

    link_counts = write_matches(result.linked + result.candidates, run_id)
    unmatched_changed = write_unmatched(result.unmatched)

    title, body = build_pr(run_id=run_id, stats=stats, result=result, link_counts=link_counts, health=health)

    has_changes = any(link_counts[k] for k in ("added", "updated")) or unmatched_changed
    PR_OUTPUT_DIR.mkdir(exist_ok=True)
    (PR_OUTPUT_DIR / "has_changes.txt").write_text("true" if has_changes else "false")
    (PR_OUTPUT_DIR / "title.txt").write_text(title)
    (PR_OUTPUT_DIR / "body.md").write_text(body)

    state["sources"] = {s.name: {"record_count": s.record_count} for s in stats}
    state["siteguide_au"]["version_id"] = siteguide.current_version_id
    _save_state(state)

    print(title)
    print(body)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
