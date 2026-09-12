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
| Fédération Française de Vol Libre | `ffvl` | FR + DOM | built and ranked; bulk file behind an API key not yet granted |

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
individual clubs).

**FFVL** is built and ranked but not yet fetching: everything is in place
(adapter, tests, offline calibration) except the key. `data.ffvl.fr` answers
its bulk sites file with a gate notice; an API key is requested per
application from `informatique@ffvl.fr`, and new requests have been suspended
at times. The fetch sends `FFVL_API_KEY` when it is set and fails loudly with
the gate notice when it is not — it never publishes an empty catalogue. Until
the key arrives the adapter is deliberately not registered in
`src/sources/__init__.py`, so the weekly run is untouched; activation is one
registration line plus the `FFVL_API_KEY` secret, then a live run. The
app's existing FFVL key (weather beacons) is a different credential and does
not unlock this file.

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
Where it comes from, in order: the guide's own `asl`/`amsl` figure, then
another guide's altitude for the same launch (PGE's takeoff altitude), then the
Copernicus DEM GLO-90 for Site Guide launches nothing else covers. The
label matters because Site Guide's `height` is free text that lists
heights-above-ground first as often as not ("3100' / 945m agl; 3540' / 1080m
asl") — parsing goes by the label, so an `agl`-only value publishes nothing
rather than an AMSL off by the height of the hill. Landings stay bare: their
altitude feeds the app's launch-minus-landing drop, which is a decision of its
own.
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
- [ ] FFVL — terms unknown; the adapter ships a blank licence and the key
      application to `informatique@ffvl.fr` asks for them. No FFVL rows are
      published until the key arrives, so nothing is redistributed in the
      meantime.

The DEM fallback is not a site guide but terrain data: [Copernicus DEM
GLO-90](https://spacedata.copernicus.eu/web/cscda/data-access) (© ESA,
[CC BY 4.0](https://spacedata.copernicus.eu/documents/20124/0/Copernicus+DEM+Dataset+Access+License)), read in batches through
[Open-Meteo's elevation API](https://open-meteo.com/en/docs/elevation-api).
It fills only ANSG launches no guide states an altitude for, and a run where
the API is unreachable simply publishes those rows without an altitude.

## Running locally

```bash
pip install -e ".[dev]"
pytest                                        # 265 tests, no network

python -m src.pipeline --dry-run --scope au   # fast: Australia only
python -m src.pipeline                        # global, ~60s (one PGE fetch)

python -m scripts.calibrate dhv de at ch      # is 250m right for a new guide?
FFVL_SITES_PATH=<file> python -m scripts.calibrate ffvl fr gp mq gf re pf nc
                                              # FFVL, offline via a saved export
```

## Weather stations

`app/site_weather_stations.csv` gives each ANSG launch - and PGE's Australian
rows with it - its nearest Weather Underground personal weather station, so the
app can show what the wind is doing *at* the hill rather than at an airport
40 km away. The main catalog is untouched; this is a separate list keyed by
`site_ref`.

The match rule: nearest station first, **on-site** within 200 m, **nearby**
within 2 km (flagged - a station 2 km away and downhill does not describe the
wind on the hill), nothing beyond. `obs_station_qc` and
`obs_station_last_obs_epoch` come free in the discovery response, so a dead or
unQC'd station is visible without spending another call. An unmatched site
still gets a row with the station columns empty - no station nearby is a
finding too.

The economics: the only quota-spending call is discovery
(`v3/location/near`, 1500/day and 30/minute on the key, shared with the
app's map layer). That response carries every station's coordinates, so the
200 m matching is offline work against a persistent cache
(`state/pws_station_cache.json`, checkpointed after every probe). A site the
cache can already answer for - any station within 2 km of it - is never
probed, so the first run costs ~150–300 calls and every re-run ~zero.

```bash
WUNDERGROUND_API_KEY=... python -m scripts.wu_pws_stations
                                              # probe where the cache is silent
python -m scripts.wu_pws_stations --cache-only
                                              # offline rematch, no key needed
python -m scripts.wu_pws_stations --sources ansg,pge-au --networks wu-pws,bom
                                              # PGE AU rows too, BOM AWS in the pool
```

The match pool is **source-blind**: WU PWS, Bureau of Meteorology AWS stations
(8 bulk XML files per run, no key, ~870 stations) and Holfuy share one cache
under namespaced ids (`wu-pws:<id>`, `bom:<wmo>`, `holfuy:<id>`), and the
nearest *alive* station wins whatever network it belongs to - alive meaning
fresher than the network's cadence allows (24 h for WU, 40 min for BOM and
Holfuy), with the nearest dead station as fallback and flagged in the columns.
`obs_source` records which network won; BOM rows link to the station's
reg.bom.gov.au page and carry its elevation.

The pool is the one thing that gates a station, so it is exactly what
`--networks` names: WU and BOM stations already cached stay in the pool whether
or not a run fetched them (as they always have), while Holfuy enters **only**
when named. That matters because of licensing, below.

### Holfuy

Holfuy is a *catalogue*, not a discovery endpoint. Its WU-style "what is near
this point" query does not exist, its official API is password-gated per
station with a documented ceiling of 3 stations, and the map overview that
would have carried a bulk list was retired in 2026-09. What remains is public
but undocumented: a keyless directory (`/puget/search.php`) listing every
station as an id and a name, and the station monitor page, which
server-renders its own coordinates into the "SHOW ON MAP" link. So the build is
a one-time walk - ~1,750 sequential requests paced ~1 s apart - and everything
after it is offline.

```bash
python -m scripts.wu_pws_stations --catalogue-only
                                              # LIVE: builds the catalogue, ~30 min
python -m scripts.wu_pws_stations --catalogue-only --refresh-holfuy
                                              # re-read every page (moved station)
python -m scripts.wu_pws_stations --sources ansg,pge-au \
    --networks wu-pws,bom,holfuy
                                              # match with Holfuy in the pool
```

The build is resumable: stations an earlier catalogue already resolved are
carried over, progress is checkpointed after each country, and the shared cache
is not touched until the completeness gate passes (fewer than 90% of directory
ids resolved fails the run - a silent partial catalogue is the failure the app
cannot see). A circuit breaker aborts after 10 consecutive failures rather than
grinding through 1,573 404s.

**A refusal is reported as a refusal, not as missing data.** `holfuy.com`
refuses connections by IP - observed as TCP "Connection refused" on
162.55.38.193, and as an HTTP "Access blocked" page from datacenter ranges - and
that now raises `HolfuyUnreachable` rather than being counted as stations whose
pages lost their map link. A one-request preflight (`?countries`, the build's
own first input, so a passing check costs no extra fetch) catches it before the
93-country walk starts, and the message names the fix. Run it from a workstation
IP by hand, never from CI: the whole design assumes this is not a recurring job,
and no retry or reordering clears an IP-level block.

A 404 is deliberately *not* folded into that: a station that has gone away is a
finding about that station, so it is counted and the walk continues.

**Licensing.** Holfuy's directory and names are Holfuy's compilation, and
permission is not on file, so Holfuy rows stay out of shipped output. Two
things enforce that, and both are load-bearing: a Holfuy-inclusive run writes
`app/site_weather_stations.holfuy-preview.csv` instead of the shipped
`app/site_weather_stations.csv`, and `holfuy` is excluded from the match pool
unless `--networks` names it - without that, a station already in the cache
would win a default run on distance and land in the published file. The
catalogue itself is gitignored, because `state/` is committed by the weekly
sync and tracking it would redistribute the compilation; only the coordinates
enter the shared cache, on the reading that a coordinate is a fact and a
curated directory is not. When permission arrives, publishing Holfuy rows is
`--networks wu-pws,bom,holfuy` plus a live run.


## CI

`.github/workflows/sync.yml` runs weekly and on manual dispatch, opening a PR
only when something changed. A source whose record count drops more than 20%
run-over-run aborts the run rather than proposing to delete a country.
