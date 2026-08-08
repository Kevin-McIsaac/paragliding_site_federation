"""The PR body: lead verdict, collapsible sections, rendered-report links."""

from src.clustering import Cluster
from src.run_summary import SourceStats, build_pr, check_health, report_link
from tests.conftest import record

_COUNTS = {"sites": 10, "countries": 1, "written": 1, "unchanged": 0}


def _body(*, stats=None, clusters=(), review=(), duplicates=(), overrides=(),
          records=(), forced=frozenset(), health=None):
    stats = stats or [SourceStats("pge", 240, 140)]
    _, body = build_pr(
        run_id="2026-08-08",
        stats=stats,
        site_counts=_COUNTS,
        clusters=list(clusters),
        review=list(review),
        duplicates=list(duplicates),
        override_entries=list(overrides),
        records=list(records),
        forced_applied=set(forced),
        health=health or check_health(stats, {}),
        no_wind=2,
    )
    return body


def test_clean_run_leads_with_no_action_required():
    assert "✅ **No action required.**" in _body()


def test_a_stale_override_promotes_the_warning_to_the_top():
    """A key that no longer resolves silently overrides nothing - the one
    failure a reader could not spot unaided."""
    overrides = [{"a": "pge:999", "b": "siteguide_au:a", "verdict": "never"}]

    body = _body(overrides=overrides, records=[record("siteguide_au", "a")])

    assert "⚠️ **1 item(s) need attention.**" in body
    assert "key not found" in body


def test_a_forced_merge_that_did_not_apply_is_flagged():
    overrides = [{"a": "pge:1", "b": "siteguide_au:a", "verdict": "always"}]
    recs = [record("pge", "1"), record("siteguide_au", "a")]

    assert "forced merge did not apply" in _body(overrides=overrides, records=recs)
    applied = {frozenset({"pge:1", "siteguide_au:a"})}
    assert "did not apply" not in _body(overrides=overrides, records=recs, forced=applied)


def test_sections_needing_attention_open_and_the_rest_collapse():
    overrides = [{"a": "pge:999", "b": "siteguide_au:a", "verdict": "never"}]

    body = _body(overrides=overrides, records=[record("siteguide_au", "a")])

    assert "<details open>" in body           # the overrides section
    assert "<details>" in body                # everything else
    assert "<summary>⚠️ <b>Overrides</b>" in body


def test_every_section_appears_even_when_empty():
    """A missing section reads as 'did that step run?', not 'nothing found'."""
    body = _body()
    for title in ("Sources", "Dataset", "Merged launches", "Unmerged near-misses",
                  "Possible duplicates within one source", "Overrides"):
        assert f"<b>{title}</b>" in body, title


def test_body_does_not_inline_report_tables():
    """The dashboard must not grow with the dataset - that was the point."""
    pge, au = record("pge", "1"), record("siteguide_au", "a")

    body = _body(clusters=[Cluster((pge, au))], records=[pge, au])

    assert "| PGE Name |" not in body
    assert "reports/merged.md" in body


def test_report_links_point_at_the_rendered_file_in_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/federation")
    monkeypatch.setenv("PR_BRANCH", "sync/federation")

    assert report_link("review.md") == (
        "[reports/review.md](https://github.com/acme/federation"
        "/blob/sync/federation/reports/review.md)"
    )


def test_report_links_degrade_to_a_path_outside_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert report_link("review.md") == "`reports/review.md`"


def test_health_failure_opens_the_sources_section():
    stats = [SourceStats("pge", 100, 60)]
    body = _body(stats=stats, health=check_health(stats, {"pge": 240}))
    assert "⚠️ <b>Sources</b>" in body


def test_source_table_still_reports_wind_coverage():
    body = _body(stats=[SourceStats("pge", 240, 140), SourceStats("siteguide_au", 245, 233)])
    assert "| pge | fetched | 240 | 140 (58%) |" in body
    assert "| siteguide_au | fetched | 245 | 233 (95%) |" in body
