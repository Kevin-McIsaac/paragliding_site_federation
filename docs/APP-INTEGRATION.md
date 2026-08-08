# App integration plan

Status: proposed. Covers switching `the_paragliding_app` from its PGE-only
bundled CSV to the federated dataset this pipeline publishes.

## What the research changed

Four findings from reading the app, each of which moves a decision:

**Flight history does not depend on site IDs.** `flights.launch_site_id` is a
foreign key to `sites(id)` — the user's own site records — not to
`pge_site_id`. Losing or remapping `pge_site_id` costs wind/altitude
enrichment and favourite identity, **not flight history**. The ID-churn risk
that shaped much of the pipeline design is therefore far smaller than assumed
on the app side. It still matters, but a bad migration degrades display, it
does not destroy a logbook.

**`last_edit` is already broken.** `parseDownloadedData` reads the column, but
`importSitesData`'s insert map omits it, so `last_edit` is NULL for every row
after a bulk import. `PgeIncrementalSyncService._getMaxLastEdit()` therefore
returns null on every run and silently falls back to "modified in the last 30
days". The incremental sync has never worked as designed. That removes
`last_edit` as an argument for anything — it is a bug to fix or a feature to
retire, not a constraint on the CSV.

**`altitude` has far more consumers than expected.** Not three screens but
nine call sites: `manage_sites_screen`, `edit_site_screen`,
`site_details_dialog`, `site_selection_dialog`, `map_overlays`,
`site_marker_layer`, `nearby_sites_screen`, `database_reset_helper`, plus the
row mapper itself. Dropping it is not a small trim.

**The CSV column order differs and would corrupt silently.** The app parses
positionally: `0 id, 1 name, 2 longitude, 3 latitude, …` — **longitude before
latitude**. Ours is `id, name, latitude, longitude`. Swapping those puts every
site in the wrong hemisphere with no error. This is the single most dangerous
detail in the whole migration.

## Decisions this forces

### Re-add `altitude` and `country` to the CSV

Nine altitude call sites and a country label in the flyability table say the
"only what the map needs" cut went one column too far. Both are cheap: PGE
publishes altitude, and country is already the shard key.

`country` also feeds an existing `country_codes` JOIN that turns `au` into
"Australia", so the app wants the **code**, not the name.

### Emit an integer `id` alongside the canonical one

`pge_sites.id` is `INTEGER PRIMARY KEY` and `sites.pge_site_id` is `INTEGER`.
Canonical IDs are strings (`PSF-000001`). Rather than migrate two column types
and every query, the CSV emits the numeric part as `id` (`PSF-000001` → `1`).
It is derived, stable and reversible, and `sites/<cc>.json` keeps the readable
form for review.

### Retire the incremental sync rather than fix it

It has never functioned, it points at a PGE endpoint that bypasses the
federation entirely, and a full refresh is 301 KB. Replacing a broken
delta-sync with a working full refresh is less code and less to go wrong. Drop
`last_edit` from the CSV and delete the service.

## Plan

### Phase 1 — pipeline (this repo)

1. Add `altitude`, `country` (ISO code) and integer `id` to `app/sites.csv`.
   Column order must match the app's positional parser exactly, or be changed
   in the same commit as the parser — see the corruption note above.
2. Add a test asserting the header order verbatim, so a future column insert
   cannot silently shift latitude.

### Phase 2 — app: swap the source

Files: `pge_sites_download_service.dart`, `pge_sites_database_service.dart`,
`database_helper.dart`.

3. Replace `assets/data/world_sites_extracted.csv.gz` with the federated CSV,
   gzipped.
4. Update `_parseCsvLine` indices and the `dbData` map to the new column
   order. **Verify with a coordinate spot-check on a known site**, not just a
   row count — a lat/lng swap parses cleanly.
5. Add `source TEXT` to `pge_sites` so a row can say where it came from; the
   detail dialog can then link to the right guide instead of assuming PGE.
6. Migration `databaseVersion` 3 → 4, following the existing `if (oldVersion <
   N)` pattern:
   - build a `pge_id → canonical_id` map from the new CSV's `source` column
   - rewrite `sites.pge_site_id` through it
   - log how many rows were remapped and how many found no match, per the
     project rule that a data migration must be auditable afterwards
7. Preserve `is_favorite` across the re-import. `importSitesData` currently
   `DELETE`s then re-inserts, which drops favourites on every refresh — an
   existing bug that this migration would otherwise inherit and make visible.

### Phase 3 — app: refresh without a release (optional)

8. Fetch the CSV from `raw.githubusercontent.com` on the existing 30-day
   timer, falling back to the bundled asset. The pipeline runs weekly but a
   bundled asset only updates when you ship a build; this closes that gap
   while keeping the offline-first guarantee that matters at launch sites with
   no signal.

## Verification

- **Coordinate spot-check first.** Pick three known sites across hemispheres
  and assert lat/lng land within metres of the published values. Row counts
  and "it parsed" prove nothing against a column-order bug.
- Drive the migration directly in a test rather than duplicating its SQL, per
  `test/duration_backfill_test.dart` — annotate it `@visibleForTesting`.
- Test the **upgrade** path from a v3 database with existing
  `sites.pge_site_id` values, not just a fresh install, and assert flights
  still resolve to their sites afterwards.
- Confirm flyability still renders for Australian sites that came from Site
  Guide — they carry parsed wind, and that is the feature the whole federation
  was for.
- Check a site whose `pge_site_id` finds no canonical match degrades to
  "no enrichment" rather than crashing.

## Out of scope

Renaming `pge_sites` to something honest (it is no longer PGE-only). Correct,
but it touches a dozen files and is better done once the switch is proven.
