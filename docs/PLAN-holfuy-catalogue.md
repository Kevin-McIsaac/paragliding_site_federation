# Plan: Holfuy station catalogue

Status: approved in principle 2026-09-11. Decisions below are the owner's four
answers, recorded so the build does not re-litigate them.

Adds **Holfuy** as a third station network beside `wu-pws` and `bom`, feeding
the same `Station` → `Cache` → `match_row` path so matching stays source-blind.

The one thing that makes this different from the other two networks: **Holfuy
publishes no discovery endpoint of any kind.** WU answers "what is near this
point"; BOM dumps a whole state. Holfuy answers neither, so this is not an
adapter — it is a **catalogue build** that walks a directory and scrapes one
number pair off each station's public page, once.

## Decisions (owner, 2026-09-11)

| Question | Answer |
|---|---|
| Fetch strategy | **Live-only, strict throttling** (~1 req/s, identifying User-Agent) |
| Coverage | **Global** — every station in the directory |
| Licensing | **Build now, resolve before publishing rows.** Holfuy rows stay out of shipped output |
| Refresh | **Manual only** — coordinates and the station list change rarely |

## Size — measured, not estimated

From `search.php?countries` (archived 2025-11 snapshot; live count re-confirmed
at build time):

| | |
|---|---:|
| Countries | 93 |
| Stations | 1,573 |

Where they are (top 10, i.e. where this actually earns its place):

| DE | NO | CH | FR | ES | AT | SE | GB | NZ | HU |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 257 | 226 | 163 | 129 | 124 | 93 | 61 | 50 | 43 | 42 |

**Cost of one full live run at 1 req/s:** 1,573 station pages (~26 min) + 93
country indexes (~1.5 min) ≈ **half an hour, ~1,670 small GETs, once.** That is
the entire impact on Holfuy, and manual-only refresh means it is not repeated on
a schedule.

## The two endpoints

Both are public and keyless.

**1. Directory** — `https://holfuy.com/puget/search.php` (undocumented; found in
`/js/main.js`). Three forms, all JSON:

```
?countries        → [{"countryCode","countryName","count"}, …]     93 rows
?country=NO       → [{"id","name"}, …]           every station in one country
?q=Bergen         → [{"id","name"}, …]           name search, ≤10 hits
```

**Coordinates are not in it.** IDs and names only. That is why there is a
second step.

**2. Coordinates** — the station monitor page `https://holfuy.com/en/weather/<id>`
server-renders its position into the "SHOW ON MAP" link:

```html
… href="https://holfuy.com/en/map/la=69.70017&amp;lo=18.63842&amp;z=14"
```

Extract with `la=([-0-9.]+)&(?:amp;)?lo=([-0-9.]+)`. Verified on three stations
in three countries:

| Station | Extracted |
|---|---|
| 142 THPK Ersfjord (NO) | 69.70017 / 18.63842 |
| 351 Elorrio-Udalaitz (ES) | 43.099772 / -2.533773 |
| 1222 Pointy Knob (US) | 39.002045 / -79.467939 |

The page also carries altitude (`130m (AMSL)`) and the station's prose blurb —
useful for review, not needed for matching.

**Timing caveat:** Holfuy discontinued the *Map overview* in 2026-09 ("The
Holfuy Map overview was discontinued in 2026 September"). The `la`/`lo` link
still renders in the HTML, but its target is retired — so **feature-detect the
field's absence** rather than assume it is permanent, and treat a run that finds
zero coordinates as a hard failure, not an empty catalogue.

## Build

### Phase 1 — fetch (`src/holfuy.py`)

Mirror `src/bom.py`'s shape: parse into `Station` records, merge into the shared
`Cache`, checkpoint after every station. The transport is injectable so tests
never touch the network, exactly as `src/pws.py` does.

- **Politeness, non-negotiable:**
  - `MIN_REQUEST_INTERVAL_S = 1.0`, via the existing `throttle(clock)` seam, so
    tests fast-forward instead of sleeping.
  - Identifying `User-Agent` — reuse `src.bom.USER_AGENT`
    (`paragliding-site-federation/1.0`). No browser spoofing.
  - **Sequential only.** No concurrency against a small operator.
  - **Circuit breaker:** abort the run after 10 consecutive failures rather than
    grinding through 1,573 404s. Abort, do not "carry on regardless".
  - Checkpoint the cache after each station so an interrupted run resumes.
- **Lighter page first:** try `http://m.holfuy.com/<id>` (the "simple mobile
  view", ~10 KB) before the full `holfuy.com/en/weather/<id>` (~48 KB). Same
  coordinates, a fifth of the bandwidth. *Unverified — confirm the `la`/`lo`
  link is present in the mobile view during Phase 1, and fall back to the full
  page if it is not.*
- **Completeness gate:** if coordinates resolve for fewer than 90% of directory
  ids, fail the run. A silent partial catalogue is exactly the failure mode the
  app cannot see.

### Phase 2 — cache and storage

- Stations merge into `state/pws_station_cache.json` under `network="holfuy"`,
  namespaced by `cache_key` (already network-aware; a Holfuy id and a BOM WMO
  number can never collide).
- A **separate**, gitignored-to-be-decided catalogue with provenance is written
  for audit: `state/holfuy_catalogue.json`, id → `{name, country, lat, lon, alt,
  url, source_page, fetched_utc}`. The cache is for matching; this is for
  reviewing what was gathered and re-runnning without refetching.
- **NETWORK_TTL_S** gets a `"holfuy"` entry. Holfuy's cadence is ~10 min, so 40
  minutes matches BOM's reasoning, but confirm the real cadence before fixing
  the number — the station page shows seconds-since-update.

### Phase 3 — output, gated on licensing

- **Holfuy does not enter default output.** `scripts/wu_pws_stations.py`'s
  `--networks` default stays `wu-pws`; Holfuy is opted into explicitly.
  ⚠️ *`--networks` currently defaults to `"wu-pws"` but the help text describes
  source-blind matching with `bom` as the example — check that adding a third
  name does not change existing invocations' behaviour, and add a test.*
- Until licensing is resolved, a Holfuy-inclusive run writes
  `app/site_weather_stations.holfuy-preview.csv`, **not**
  `app/site_weather_stations.csv`. The publish gate does not include it.
- When/if Holfuy agrees, the file merges into the normal output and
  `holfuy` joins the match pool. That is a one-line change plus a live run.

### Phase 4 — app consumption stays out of this plan

No app change is proposed here. The federation publishes the CSV; whether the
app consumes a Holfuy-inclusive column set is a separate decision that waits on
licensing. Fixing a column layout now would guess at an app change that may
never be approved.

### Phase 5 — tests (`tests/test_holfuy.py`, no network)

- Parse a fixture of the real monitor page → assert both coordinates.
- The directory parse (countries / country / q) against saved fixtures.
- `&amp;` vs `&` in the link — the real page emits `&amp;`; assert both parse.
- Throttle honours the interval using a fake clock.
- Circuit breaker trips at 10 consecutive failures.
- Cache merge namespaces under `holfuy` and does not collide with same-numeric
  WU/BOM ids.
- **Negative test:** a monitor page with no map link contributes no station and
  is counted, rather than silently parsed as 0,0. (A 0,0 station off the coast
  of Africa would match nothing and look like coverage.)

## Verification (do not skip to the end state)

- **Spot-check three known stations across hemispheres** against the table
  above. A coordinate-transposition bug parses cleanly and puts stations in the
  wrong hemisphere, which no row count catches — the same trap `app/sites.csv`
  documents.
- **Measure the distance distribution** of matched sites. For the Alps, a
  Holfuy station within 2 km of a launch should be common; if nothing matches,
  suspect the parse, not the network.
- **Prove the negative:** run the extractor against a page with the map link
  removed and watch it fail loudly.
- Confirm a re-run over an already-populated cache makes **zero** network calls.

## Licensing — must be resolved before rows ship

The README's rule is that a guide's data is not redistributed until permission
is on file; both DHV and FFVL sit in that queue. Holfuy is the same shape: the
station *directory* and *names* are Holfuy's compilation, and the coordinates
are read from pages they serve. Coordinates are facts; the catalogue is not.

Owner decision is to build now and gate publication. The corresponding task is a
conversation with `info@holfuy.hu` (same avenue the API access page points at),
to be raised before any Holfuy row enters `app/sites.csv`'s companion file.

Note the asymmetry the API page states plainly: "The API-s are mainly for
station owners … we can open the actual data API for other users also for
**maximum 3** stations." We are **not** asking for API access — we do not need
it, and asking for a 1,573-station exemption would be rejected. What we would
ask is narrower: *may we keep a local, periodically-refreshed cache of the
public station directory and positions for matching launches, with attribution
and no redistribution of observation data?* The API is not the product here;
the catalogue is.

## Out of scope

- Live observations. This is positions only; `mjso.php?k=<id>` and the official
  API both supply readings and are not needed to match a launch to a station.
- Any writes back to Holfuy.
- Replacing WU PWS or BOM. Holfuy joins the pool; the nearest *alive* station
  still wins, whatever network it belongs to.

## Build environment note

`holfuy.com` and `api.holfuy.com` (162.55.38.193) answered this session's first
probes and then began refusing connections outright — a server-side firewall,
not a sandbox rule, and it persisted. `widget.holfuy.com` (79.139.59.19, a
different host) stayed reachable throughout. **Run the build from a normal
workstation IP**, not from CI or a datacenter range, and expect that a burst of
requests may get the source IP blocked. That is another argument for the
manual, checkpointed, once-only run.

## What we learned — summary notes

Kept here because none of it is written down anywhere Holfuy publishes, and
most of it contradicts the obvious search results.

1. **There is no WU-PWS-style nearby endpoint for Holfuy, official or
   community.** WU's is `v3/location/near?product=pws`; Holfuy has no
   equivalent and no reverse-engineered one exists. GitHub has only 13 Holfuy
   repositories in total, and every client does the same thing: the official
   password API or widget scraping for one known station.

2. **The official API is deliberately closed.** `api.holfuy.com/live/` is
   password-gated **per station**, with a documented ceiling of 3 stations, and
   an explicit "the stations' owners can disable the API access any time". Live
   verification: `?s=1283` → `{"errorCode":"no_access"}`, while TestStation 101
   is open and returns `location{latitude,longitude,altitude}` with `loc`. So
   `s=all&loc` — the one documented parameter that would bulk-return
   coordinates — only ever returns the stations *you already have access to*.
   It is not a public dump.

3. **The undocumented directory is the free half.** `/puget/search.php` is
   called by Holfuy's own `/js/main.js` and is unauthenticated. `?countries` and
   `?country=<CC>` give the complete global inventory — 93 countries, 1,573
   stations — as ids and names, with no coordinates and no rate-limit page
   observed. This is the piece that makes a catalogue possible without a key.

4. **Coordinates are public on the station page.** The monitor page embeds
   `map/la=<lat>&lo=<lon>&z=14` server-side. This is the fact the whole plan
   rests on. No key, no login.

5. **The map overview was retired in September 2026** — this month. Holfuy's
   own map was the natural place a bulk station list would have lived; it is
   gone, and the coordinate link still points at the dead route. Anything built
   on scraping Holfuy has a short shelf life, which is why this is a one-time
   catalogue with a feature-detection gate rather than a live discovery service.

6. **Other stations' JSON exists but has no coordinates.**
   `/puget/mjso.php?k=<id>` (undocumented, called by `/js/rtr.js`, archived)
   returns live readings — `valid`, `updated`, `speed`, `gust`, `dir` — for the
   monitor page's 30-second refresh. No position, no bulk form. `api.holfuy.com/cam/s`
   is discontinued (404, but still referenced by `map_mapbox.js`).

7. **The official apps have no nearby feature.** The iOS listing (bundle
   `hu.holfuy.app`, v2.1.3) offers favourites, graphs and archive tables — you
   must already know the station id.

8. **Third-party reuse doesn't help.** Holfuy stations can be registered with
   Windguru and Windy, and both could in principle reveal positions — but
   Windguru's station API is keyed per own-station, and Windy's now requires an
   `x-windy-api-key` (403 "Missing Header"). Neither is a discovery route.

9. **The community discussions are all about one station, never a search.**
   The canonical thread is the Home Assistant
   [multiscrape post](https://community.home-assistant.io/t/holfuy-weather-station-using-multiscrape/663061)
   (`widget.holfuy.com/?station=<id>&mode=detailed`, CSS selectors `#j_speed`,
   `#j_gust`, …), plus the HACS integration
   [stefanh12/holfuy](https://github.com/stefanh12/holfuy) and
   [haavardj/PyHolfuy](https://github.com/haavardj/PyHolfuy) — both pure
   official-API wrappers, both capped at 3 stations. Also checked and of no use
   here: `jlandmann/holfuyretriever` (camera images), `bxrne/holfuy`,
   `btomala/stacjapogoda`, `forcequit/holfuy-wow`.
