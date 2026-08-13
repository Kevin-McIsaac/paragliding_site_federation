"""Gates that stop a run replacing a good catalogue with a broken one.

Every gate here is asserted in both directions - a normal week passes, and a
specific fault trips it. A gate only ever seen passing is indistinguishable from
one that cannot fail, which is how the positional-id catalogue shipped: every
number looked healthy while every key had moved.

Numbers are set against a real week: on 2026-08-10, 13 of 11,703 launches were
withdrawn (0.11% churn), none added, and no surviving launch moved.
"""

from src.canonical_store import read_published, write_app_csv
from src.clustering import Cluster
from src.ids import IdRegistry
from src.run_summary import PublishedSite, check_output_health
from src.selection import select
from tests.conftest import record


def _site(provider, source_id, *, lat=-30.0, lon=150.0, name="A launch"):
    return select(
        Cluster(members=[record(provider, source_id, name=name, lat=lat, lon=lon)]),
        IdRegistry(),
    )


def _published(sites):
    return [
        PublishedSite(
            ref=s.ref, lat=s.lat, lon=s.lon,
            providers=frozenset(s.sources), role=s.role,
        )
        for s in sites
    ]


def _catalogue(n, *, provider="pge", start=0):
    return [
        _site(provider, str(i), lat=-30.0 + i * 0.01, name=f"Launch {i}")
        for i in range(start, start + n)
    ]


def test_an_ordinary_week_passes():
    before = _catalogue(200)
    # One launch withdrawn upstream, which is roughly the real rate.
    after = before[:-1]

    health = check_output_health(after, _published(before))

    assert health.ok, health.notes
    assert "within range" in " ".join(health.notes)


def test_a_first_run_says_so_rather_than_passing_quietly():
    health = check_output_health(_catalogue(10), [])

    assert health.ok
    assert "No published catalogue" in health.notes[0]


def test_a_collapsed_launch_count_fails():
    before = _catalogue(200)
    after = _catalogue(150)  # a partial fetch that still parsed

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert any("launch count changed" in n for n in health.notes)


def test_renumbering_every_key_fails():
    # The positional-id catalogue, reproduced: same launches, same count, same
    # coordinates - every key different. Nothing else here would notice.
    before = _catalogue(200)
    after = _catalogue(200, start=1000)

    health = check_output_health(after, _published(before))

    assert not health.ok
    churn = next(n for n in health.notes if "no longer emitted" in n)
    assert "200 of 200" in churn
    assert "loses its wind and altitude" in churn


def test_a_provider_vanishing_from_the_output_fails():
    # Records arrived - the source-count gate is happy - but they did not survive
    # clustering or selection, which is a fault on this side.
    before = _catalogue(100) + _catalogue(100, provider="ansg", start=500)
    after = _catalogue(100)

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert any("ansg: launches dropped" in n for n in health.notes)


def test_a_key_moving_a_long_way_fails():
    # How an upstream id reused for a different site looks: the key survives, the
    # launch is somewhere else entirely.
    before = _catalogue(200)
    after = list(_catalogue(199)) + [_site("pge", "199", lat=47.0, lon=12.0)]

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert any("moved more than" in n for n in health.notes)


def test_a_small_move_is_a_coordinate_correction_not_a_reuse():
    before = _catalogue(200)
    # ~1 km: a guide refining a takeoff, which happens and must not fail a run.
    after = list(_catalogue(199)) + [_site("pge", "199", lat=-30.0 + 199 * 0.01 + 0.009)]

    health = check_output_health(after, _published(before))

    assert health.ok, health.notes


def test_reads_a_snapshot_that_predates_the_ref_column(tmp_path):
    # An older published file has no `ref`, so the gate derives it by the same
    # rule that produced it - otherwise the first run after adding the column
    # would read as 100% churn and block itself.
    path = tmp_path / "sites.csv"
    write_app_csv(_catalogue(3), path)
    text = path.read_text().splitlines()
    header = text[0].split(",")
    ref_at = header.index("ref")
    rows = [",".join(c for i, c in enumerate(line.split(",")) if i != ref_at)
            for line in text]
    path.write_text("\n".join(rows) + "\n")

    published = read_published(path)

    assert [p.ref for p in published] == [s.ref for s in _catalogue(3)]


def test_a_new_guide_may_land_its_launches_in_one_run():
    """Adding a national guide is a step change the count gate would otherwise
    refuse - DHV alone is ~13% against a 5% limit."""
    before = _catalogue(200)
    after = before + _catalogue(40, provider="dhv", start=1000)

    health = check_output_health(after, _published(before))

    assert health.ok, health.notes
    assert "only from new guide(s) dhv" in " ".join(health.notes)


def test_the_allowance_expires_once_the_new_guide_is_published():
    """The same 20% growth that was allowed on arrival must fail afterwards.

    This is the whole point of deriving the allowance rather than declaring it:
    a declared one would keep excusing growth on every later run.
    """
    before = _catalogue(200) + _catalogue(40, provider="dhv", start=1000)
    after = before + _catalogue(40, provider="dhv", start=2000)

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert "launch count changed" in " ".join(health.notes)


def test_the_allowance_never_excuses_a_collapse():
    """A new guide arriving must not mask the catalogue shrinking."""
    before = _catalogue(200)
    after = before[:100] + _catalogue(5, provider="dhv", start=1000)

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert "launch count changed" in " ".join(health.notes)


def test_the_allowance_does_not_let_a_shrinking_catalogue_hide_behind_it():
    """The case `abs(delta) - allowance` missed: 150 of 200 existing launches
    survive alongside 60 from a new guide, which nets to a healthy-looking +5%
    while a quarter of the catalogue has gone. The allowance excuses the new
    guide's launches, never the ones that stopped being emitted."""
    before = _catalogue(200)
    after = before[:150] + _catalogue(60, provider="dhv", start=1000)

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert "launch count changed" in " ".join(health.notes)


def _landing(source_id, *, lat=-30.0, lon=150.0):
    from src.model import CanonicalSite
    site = _site("pge", source_id, lat=lat, lon=lon, name="A landing")
    return CanonicalSite(
        id=site.id, name=site.name, lat=site.lat, lon=site.lon, wind={},
        sources=site.sources, primary=site.primary, role="landing",
    )


def test_landings_may_land_in_one_run():
    """A third of the catalogue arrives at once, from guides already published -
    so the new-provider allowance cannot see them and the count gate would
    otherwise refuse the only run that can introduce them."""
    before = _catalogue(200)
    after = before + [_landing(f"{i}-lz", lat=-30.0 + i * 0.01) for i in range(80)]

    health = check_output_health(after, _published(before))

    assert health.ok, health.notes
    assert "new row type(s) landing" in " ".join(health.notes)


def test_the_landing_allowance_expires_once_they_are_published():
    """The same growth must fail the week after. Derived, not declared, so this
    needs no one to remember to take the allowance away."""
    before = _catalogue(200) + [_landing(f"{i}-lz", lat=-30.0 + i * 0.01) for i in range(80)]
    after = before + [_landing(f"{i}-lz2", lat=-31.0 + i * 0.01) for i in range(80)]

    health = check_output_health(after, _published(before))

    assert not health.ok
    assert "launch count changed" in " ".join(health.notes)
