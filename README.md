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

The Alps are the same story at larger scale. Adding the DHV Geländedatenbank:

| | before | after | wind before | wind after | added | merged |
|---|---:|---:|---:|---:|---:|---:|
| DE | 595 | 1,355 | 36% | 81% | 760 | 265 |
| AT | 256 | 483 | 40% | 73% | 227 | 86 |
| CH | 564 | 784 | 87% | 94% | 220 | 274 |

DHV publishes a Startrichtung for every takeoff it lists, where PGE has one for
about a third of its German sites. 1,207 of DHV's 1,832 launches had no PGE
counterpart at all — in Germany a third of those are the tow fields most of the
north actually flies from. Every one of the 625 merges kept the `pge:` key
devices already store.

## Sources

| Guide | Provider | Countries | Access |
|---|---|---|---|
| ParaglidingEarth | `pge` | worldwide | public GeoJSON API, no key |
| Australian National Site Guide | `ansg` | AU | public bulk export, no key |
| DHV Geländedatenbank | `dhv` | DE, AT, CH | public per-country KML, no key |

Adding one is: write the adapter, give it its identity (`label`, `full_name`,
`homepage`, `site_url_template` — see `sources/base.py`), list it in
`src/sources/__init__.py`, rank it in `model.KEY_PRECEDENCE`, and say where it
is authoritative in `selection.NATIONAL_SCOPE`. The last two stay hand-written
because they are decisions — which guide's id keys a launch, and which guide's
content wins. The pipeline refuses to run on an adapter that is unranked *or*
unnamed: the app renders a guide entirely from what is published about it, so an
unnamed guide would reach a phone as a bare `source` prefix with no label, no
link out and no attribution.

Two guides that publish no usable site data, checked and rejected: **Flyland**
(airspace only, and behind a login — DHV covers Switzerland instead) and
**BHPA** (clubs and schools, not flying sites; UK site data lives with
individual clubs). **FFVL** is next and does publish a good API, but its key
must be authorised per application (`informatique@ffvl.fr`).

PGE is treated as one source among peers, not as the spine. The output *is*
the dataset.

## What ships to the app

The app's core job is drawing launches on a map, which needs four things:

```
id, name, longitude, latitude, altitude, country, wind_n..wind_nw, source
```

Column order is dictated by the app, which parses positionally — it matches
the PGE-only asset it replaces field for field, with `source` in the slot
`last_edit` used to occupy. **Longitude before latitude looks wrong and is
deliberate**: reordering them parses cleanly and puts every site in the wrong
hemisphere, which no row count would catch.

That's `app/sites.csv` — 18,761 rows, 684 KB gzipped.

Altitude and country are carried because the app reads them in nine places.
Rating, hazards, access notes and landowners are deliberately absent: prose is
looked up from the guide when a user opens a site, so it doesn't need to ship
with every install.

**No prose at all now, including landing rules.** `notes` used to be the one
exception, carried for landings on the argument that landing rules are safety
information a pilot wants at a launch site with no signal.

That argument no longer holds: offline is not a design constraint for this app —
most launch sites have network access. So the column was judged on what it
actually bought, and the answer was nothing: the app displays a landing as a map
pin and a row on its launch, both linking out to the guide's own page, which
carries the hazards, access and landowner notes this column never held. 2,892
rows of prose nothing read, and **19.7% of the gzipped catalogue** a fresh
install downloads and stores — 851 KB to 684 KB.

`CanonicalSite.notes` and selection's gap-fill are unchanged. The prose is still
in `sites/<cc>.json`, which is where it is reviewed; only the app's copy is gone.

There's no `url` column either — one page address per guide beats 18,761 copies
of three templates, so those live in **`app/guides.json`** beside the rows.

That file is the second thing published to the app, and it exists because a
`source` token is a key, not a name: nothing in `sites.csv` says `dhv` is the
DHV Geländedatenbank, that a pilot should see "DHV" on a tab, or where DHV's
page for that site is. The app used to answer all three from hand-written tables,
so a guide added here stayed nameless there until someone shipped an app release.

**`{id}` in a template is the guide's id from `site_group`, not from `source`.**
This README used to say every page was "derivable from `source`", and that was
wrong in a way worth recording. A `source` id names the *launch*; these guides
publish a page per *site*, and two of the three append a suffix to reach the
launch — `pge:6824-lz`, `ansg:lz-1`. The app derived from `source` and chopped at
the first hyphen, producing `?site=6824-lz` and `/sites/details/lz`: **4,828 of
19,759 links were wrong**. `site_group` carries the site id for every provider on
every row (19,759 of 19,759), so one template per guide is correct for launches
and landings alike.

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
in `overrides.json` by hand. What it is for is calibration — a run of true
matches sitting just past the threshold means the threshold is wrong for that
region's data.

Every run writes four reports under `reports/`: `merged.md` (every merge,
widest gaps last), `review.md` (close but not merged, and why), `overrides.md`
(the readable view of `overrides.json`, keys resolved to names and stale
entries flagged), and `duplicates.md`.

`merged.md` earns its place because selection keeps only the winner's name —
once Site Guide's `Wagga (80m dunes)` wins, PGE's `80 Meter Dunes` survives
nowhere else. It will want sharding per country once a third source lands.

To override the automatic decision, copy a **Keys** cell from any report into
`overrides.json` and set a verdict: `never` keeps a pair apart, `always`
forces it together regardless of distance. Malformed entries fail the run
rather than being skipped, since an ignored override looks exactly like one
that was never applied.

That last one covers a gap cross-source matching cannot: PGE carries both
`Little Europe` and `Lake St Clair` 133 m apart, and Site Guide's single launch
there is named `Glennies Ridge - Lake St Clair (Little Europe)` — one place,
entered twice. Only the nearer PGE record can merge, so the other shows in
`REVIEW.md` as *counterpart already merged*. These are never merged
automatically, because telling a duplicate from a deliberate neighbour needs
judgement — `Tasman Flying Site 3` and `4` are 35 m apart facing `E-NE` and
`W-NW`. The report shows both sides' wind, which is the clearest tell, and
skips launches sharing a parent site since those are distinct by definition.

Records from the *same* source are never compared — one guide listing several
launches at a site is a deliberate distinction, not a duplicate.

Distance is the only signal every source publishes comparably. Names differ
by convention ("Blackheath" vs "Main launch"), altitude mixes ASL with AGL,
and wind is absent or prose-encoded depending on source. An earlier weighted
model combining all four produced a confidence number that was hard to reason
about and impossible to explain in a review.

Two refinements: a record joins a cluster only if it's within 250 m of
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
- [ ] DHV — confirmed OK to redistribute derived/merged data. The Geländedaten
      KML export is public and needs no login, but DHV publishes no terms with
      it, so this is a conversation rather than a licence to read
      (`gelaendeinfo@dhv.de`).

## Running locally

```bash
pip install -e ".[dev]"
pytest                                        # 143 tests, no network

python -m src.pipeline --dry-run --scope au   # fast: Australia only
python -m src.pipeline                        # global, ~60s (one PGE fetch)

python -m scripts.calibrate dhv de at ch      # is 250m right for a new guide?
```

## CI

`.github/workflows/sync.yml` runs weekly and on manual dispatch, opening a PR
only when something changed. A source whose record count drops more than 20%
run-over-run aborts the run rather than proposing to delete a country.
