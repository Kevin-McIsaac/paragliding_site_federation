# v2 — canonical dataset, PGE as a peer source

Status: proposed, not implemented. Supersedes the v1 link-overlay model in
the README once built.

## Context

v1 treats PGE as the spine: every output file is a link keyed
`<pge_id>__<source>-<source_id>.json`, and a source site with no PGE
counterpart goes to a worklist rather than into the dataset.

The first real run measured the cost of that: **135 of 245 Site Guide AU
launches had no PGE counterpart**. Under v1 they stay invisible to the app
until PGE's maintainers accept them upstream — a process outside our control
and on nobody's schedule. PGE returned 239 sites for the whole of Australia;
Site Guide alone lists 245 launches for its clubs. PGE's AU coverage is thin,
and the spine design inherits that thinness as a ceiling.

v2 makes the pipeline's output the integrated dataset in its own right. PGE
becomes one source adapter among peers. The app loads the canonical dataset
instead of PGE's world CSV.

A second benefit is the failure mode inverting. Under v1 a missed match means
a site is **absent**; under v2 it means a **duplicate** — two canonical sites
where there should be one. Duplicates are visible, reportable and fixable next
run. Absences are silent. This materially de-risks the scoring weakness found
in the first run (sources lacking orientation/altitude data cap otherwise-
perfect matches near 0.82).

## Model

A **canonical site** is a cluster of one or more source records believed to be
the same physical launch, with:

- a stable synthetic `id` (`PSF-000001`), never reused, never renumbered
- `sources`: every contributing source key, e.g.
  `{"pge": "4632", "siteguide_au": "106-28"}`
- the selected record's fields, with provenance per the rule below

A cluster of one is normal — most of the 11.4k PGE sites have no peer.

## Fetch

- **PGE, global, one request**:
  `getBoundingBoxSites.php?north=90&south=-90&west=-180&east=180` returns the
  complete dataset (11,437 sites / 137 countries, verified against the
  per-country endpoint: 238 vs 239 for AU). This is what
  `bin/fetch_pge_sites.sh` in the app repo already does. The v1 tiled adapter
  is replaced by this and deleted.
  `getCountrySites.php?iso=<cc>` exists as a per-country alternative and is
  useful for validation and for scoping test runs.
- **Site Guide AU**: unchanged — `/api/Version` gate, then `/api/Export`.

PGE properties worth parsing that v1 ignores: `takeoff_description`,
`landing_lat`/`landing_lng`, `takeoff_parking_lat`/`lng`, `pge_link`,
`last_edit`, and the `thermals`/`soaring`/`xc`/`winch`/`flatland`/
`hanggliding`/`paragliding` flags.

`ffvl_site_id` is present in PGE's schema (empty for AU, presumably populated
for France). A future FFVL adapter should match on it directly rather than on
geometry — an explicit key beats any score.

## Clustering

Pairwise scoring, gates and bands are unchanged from v1. What changes is that
matching is now N-way and symmetric, so clustering must be **more conservative
than pairwise matching** to avoid transitive fusion: A~B and B~C must not
silently produce one site from three.

Rule: a record joins a cluster only if it scores above the auto-link threshold
against **every** existing member, not merely against one. A pair that only
links transitively is emitted as a flagged review item, not merged.

## Record selection

**Whole-record wins, loser fills gaps.** One source is selected per cluster by
declared precedence (national guide over PGE for the countries it covers), and
its values are used — but any field it leaves null or empty falls back to the
next source in the cluster.

The gap-fill is not optional polish. Site Guide AU carries no wind data at
all, while PGE has orientation flags for every site, and the app feeds
`site.windDirections` directly into `flyability_cell.dart` and its 7-day
forecast table. Strict whole-record selection would break flyability on
precisely the sites this project set out to improve.

Each canonical record therefore carries `field_sources` for any gap-filled
field, so the origin of a value is never ambiguous.

## ID stability

User flight history references site IDs, so churn is a data-loss bug, not a
cosmetic one.

`state/id_registry.json` maps every source key → canonical id and is committed
with the dataset. Rules:

- a cluster whose source keys are all unknown → freshly allocated id
- a cluster containing known keys → inherits the **lowest** canonical id among
  them (deterministic under reordering)
- a split cluster: the part holding that anchor id keeps it, the remainder is
  allocated new ids
- ids are never reused, even after a site is removed upstream

## File layout

One file per country, `sites/<cc>.json`, sorted by canonical id — 137 files,
largest ~1,078 sites (France). One file per site would be 11.4k files and
unusable in GitHub's diff view; one global file would make every diff a
whole-file rewrite. Country files keep a single site's change to a readable
few-line diff.

`links/` and `links/candidates/` are retired. Rejection tombstones survive as
`rejections.json` — a declined merge must stay declined, or the next run
re-proposes it forever.

## App migration (separate follow-up, not this plan)

The canonical record's `sources.pge` field is the migration key: the app maps
its existing `sites.pge_site_id` → canonical id locally in a normal schema
migration, then switches `pge_sites` to the canonical table. No extra mapping
artifact needs shipping. Global coverage means no regression outside Australia
— non-AU sites are simply clusters of one.

## Verification

- Unit tests for clustering must cover the transitive case explicitly: A~B,
  B~C, A≁C must yield two clusters plus a flagged item, never one cluster.
- ID stability test: run twice over the same input, assert zero id changes;
  run with one source record removed, assert surviving ids are unchanged.
- Gap-fill test: an AU cluster where Site Guide wins must still carry PGE's
  wind directions.
- A live dry run against both sources, checking the AU cluster count lands
  near 239 PGE + 245 Site Guide − (matched pairs), and spot-checking a sample
  of clusters by hand before the first PR is merged.

## Open item — licensing

v2 makes redistribution central rather than incidental: the pipeline now
publishes a merged dataset intended to be the app's primary source. Confirmed
permission from PGE and Site Guide AU maintainers gates the app's switchover
(decision recorded: contact before the app ships, not before further pipeline
work).
