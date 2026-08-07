# Paragliding Site Federation

Merges national paragliding site guides with
[ParaglidingEarth](https://www.paraglidingearth.com) (PGE) into one list of
launches, published as reviewed pull requests. Nothing is written back into
PGE or any other guide.

## Why

PGE is global and community-maintained, but several countries run their own
better-curated guides. Australia is the worked example: of 245 Site Guide AU
launches, **135 have no PGE counterpart at all**, and PGE is missing wind
directions for **42% of its Australian sites** where Site Guide is missing
them for 5%. Federating adds both coverage and data quality.

PGE is treated as one source among peers, not as the spine. The output *is*
the dataset.

## What ships to the app

The app's core job is drawing launches on a map, which needs four things:

```
id, name, latitude, longitude, wind_n..wind_nw, source
```

That's `app/sites.csv` — 11,692 launches, 301 KB gzipped, near-identical in
size to the PGE-only asset it replaces despite carrying 255 more launches.

Everything else — altitude, rating, hazards, access notes, landowners — is
deliberately absent. It's looked up from the source when a user opens a site,
so it doesn't need to ship with every install. There's no `url` column either:
every source page is derivable from `source` (`pge:4632` →
`paraglidingearth.com/?site=4632`, `siteguide_au:106-28` →
`siteguide.org.au/sites/106`).

`sites/<cc>.json` is the richer per-country form that lives in git for review
and provenance.

## The unit is a launch, not a site

PGE models one record per takeoff. Site Guide nests launches under a site,
and **only launches carry coordinates** — the site is a named area holding
metadata. A launch is therefore the same unit as a PGE record, and that's
what a row is.

Mostly they coincide (224 of 245 Site Guide sites have exactly one launch).
The exceptions cut both ways: `Manilla - Mt Borah` is one lumped PGE record
but four Site Guide launches spread ~300m; `Long Reef` is three PGE records
against two Site Guide sites.

## Deduplication

Across sources only, on distance alone:

| Distance | Outcome |
|---|---|
| < 250 m | merged |
| 250–400 m | reported in `REVIEW.md`, not merged |
| > 400 m | separate launches |

The 250 m threshold was calibrated, not guessed. At 100 m the review band held
21 undecided pairs and reading them showed essentially all were the same
launch under different naming conventions — `Hill 60` ~ `Hill 60` at 110 m,
`Cape Jervis` ~ `Cape Jervis` at 173 m. A review step there would have meant
hand-confirming the default 21 times. `REVIEW.md` is therefore a **report, not
a worklist**: nothing in it needs action, and the rare genuine exception goes
in `rejections.json` by hand. What it is for is calibration — a run of true
matches sitting just past the threshold means the threshold is wrong for that
region's data.

Records from the *same* source are never compared — one guide listing several
launches at a site is a deliberate distinction, not a duplicate.

Distance is the only signal every source publishes comparably. Names differ
by convention ("Blackheath" vs "Main launch"), altitude mixes ASL with AGL,
and wind is absent or prose-encoded depending on source. An earlier weighted
model combining all four produced a confidence number that was hard to reason
about and impossible to explain in a review.

Two refinements: a record joins a cluster only if it's within 100 m of
**every** member (otherwise A–B–C chains fuse distinct launches), and ~12
Tasmanian sites that publish deliberately approximate coordinates
("available to THPA members") are never auto-merged, since proximity there is
coincidence rather than evidence.

When a merge happens, the national guide supplies name and position inside
its own country; PGE wins everywhere else.

## Wind directions

Site Guide has no structured orientation field — it publishes prose in
`conditions`: `"E-NE"`, `"SSW to SSE"`, `"NW- WSW (best WNW)"`,
`"North East"`. `src/wind.py` parses it, which matters because the 135
AU-only launches have no other possible source of wind data. Coverage is 95%.

Ranges take the shorter arc (`NW-SW` means NW→W→SW), commas separate entries,
parentheticals are advisory, and `All`/`Any`/`Various` mean every direction.
Output is on the app's 8-point compass.

One accepted consequence: PGE grades directions 0/1/2 (none/good/excellent)
and parsed prose can only say "in range" (1), so a Site Guide-primary launch
never shows "excellent".

## Licensing — must be resolved before the app ships

This publishes a merged, derived dataset intended to become the app's primary
source. Both sources expose key-less public read APIs that
[the_paragliding_app](https://github.com/Kevin-McIsaac/the_paragliding_app)
already consumes for display, but that does not by itself cover
redistribution.

- [ ] PGE — confirmed OK to redistribute derived/merged data
- [ ] Site Guide AU — confirmed OK to redistribute derived/merged data

## Running locally

```bash
pip install -e ".[dev]"
pytest                                        # 57 tests, no network

python -m src.pipeline --dry-run --scope au   # fast: Australia only
python -m src.pipeline                        # global, ~60s (one PGE fetch)
```

`--force` ignores the Site Guide version gate and refetches regardless.

## CI

`.github/workflows/sync.yml` runs weekly and on manual dispatch, opening a PR
only when something changed. A source whose record count drops more than 20%
run-over-run aborts the run rather than proposing to delete a country.
