"""The PR body's source table and the run-health gate."""

from src.run_summary import SourceStats, build_pr, check_health

_COUNTS = {"sites": 10, "countries": 1, "written": 1, "unchanged": 0}


def _body(stats):
    _, body = build_pr(
        run_id="2026-08-08",
        stats=stats,
        site_counts=_COUNTS,
        merged_clusters=3,
        review=[],
        health=check_health(stats, {}),
        no_wind=2,
    )
    return body


def test_source_table_reports_wind_coverage():
    body = _body([SourceStats("pge", 240, 140), SourceStats("siteguide_au", 245, 233)])

    assert "| Source | Status | Records | With wind directions |" in body
    assert "| pge | fetched | 240 | 140 (58%) |" in body
    assert "| siteguide_au | fetched | 245 | 233 (95%) |" in body


def test_wind_coverage_handles_a_source_with_no_records():
    assert SourceStats("pge", 0, 0).wind_coverage == "—"


def test_health_aborts_when_a_source_collapses():
    stats = [SourceStats("pge", 100, 60)]
    health = check_health(stats, {"pge": 240})
    assert not health.ok
    assert "dropped" in health.notes[0]


def test_a_skipped_source_is_not_treated_as_a_collapse():
    stats = [SourceStats("siteguide_au", 0, 0, skipped_unchanged=True)]
    assert check_health(stats, {"siteguide_au": 245}).ok
