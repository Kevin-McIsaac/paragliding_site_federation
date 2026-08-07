# Paragliding Site Federation

Merges national paragliding site guides with
[ParaglidingEarth](https://www.paraglidingearth.com) (PGE) into one canonical
dataset, published as reviewed pull requests. Nothing is ever written back
into PGE or any other guide.

## Why

PGE is global and community-maintained, but several countries run their own
better-curated guides. An earlier design treated PGE as the spine and only
recorded cross-references to it — until the first real run showed **135 of 245
Site Guide AU launches have no PGE counterpart at all**. Under that design
they were invisible to the app indefinitely, waiting on a PGE submission
process nobody controls.

So PGE is now just another source. The pipeline's output *is* the integrated
dataset. Coverage is the union of every source, not the intersection with PGE.

v1 covers PGE (global) and [Site Guide AU](https://siteguide.org.au). DHV,
FFVL, Flyland and BHPA are follow-on adapters; none have been checked for
usable public data yet. PGE publishes an `ffvl_site_id` column, so an FFVL
adapter should match on that directly rather than on geometry.

## How it works

A scheduled GitHub Action re-fetches every source, matches and merges, and
opens one pull request per run. Merging the PR is the publish step.

### Matching

Two records are compared only if they come from **different** sources (one
guide listing several launches at a site is a deliberate distinction, not a
duplicate), share a role (launch/landing), and sit within 750m. Four signals
combine into a 0–1 confidence score:

| Signal | Weight | Notes |
|---|---|---|
| Distance | 0.45 | Linear decay to 0 at 500m |
| Wind orientation overlap | 0.25 | |
| Name similarity | 0.20 | Fuzzy, token-sorted |
| Altitude difference | 0.10 | |

**Weights are renormalized over the signals actually available for a pair.**
Substituting a neutral 0.5 for missing data (the original approach) meant Site
Guide AU publishing no wind orientation left 0.35 of the weight permanently
neutral, capping even a zero-distance identical-name match near 0.82 and
pushing 66 of 79 real matches into manual review. Scoring a pair on what is
known about it fixed that.

Minus 0.15 if the two records disagree on country. An explicit cross-reference
already present in either record short-circuits to a confirmed match.

**Bands**: ≥0.80 merges · 0.30–0.80 becomes a review item · below 0.30 is
discarded.

### Clustering

Records merge into a canonical site only if each one clears 0.80 against
**every** existing member, not just one. Without that, A~B and B~C silently
chain three distinct launches into a single site. Pairs that would only have
linked transitively become review items instead.

### Record selection

Whole-record wins: one source is selected per cluster (a national guide
outranks PGE inside its own country), and its values are used — but **any
field it leaves empty falls back to the next source**, recorded in
`field_sources`.

That gap-fill is load-bearing, not polish. Site Guide AU publishes no wind
orientation at all, while the app feeds `windDirections` straight into its
flyability calculation. Strict whole-record selection would blank out
flyability on precisely the sites this project set out to improve.

### Output

`sites/<cc>.json`, one file per country, sorted by canonical id. One file per
site would be 11.7k files (unusable in GitHub's diff view); one global file
would make every change a whole-file rewrite.

Canonical ids (`PSF-000001`) are stable and never reused — the app's flight
history references them, so churn is data loss. `state/id_registry.json` maps
every source key to its id. A cluster inherits the lowest id among its known
members; when a cluster splits, the first half assigned keeps the id and the
rest get fresh ones.

`review.json` holds pairs worth a look — near-misses and transitive-only
links. To decline a merge permanently, add the pair to `rejections.json`:

```json
[{"a": "pge:4632", "b": "siteguide_au:106-28",
  "reason": "distinct N- and S-facing launches on the same ridge"}]
```

Without that, a rejected match is re-proposed every run, forever.

## Licensing — must be resolved before the app ships

This publishes a *merged, derived* dataset intended to become the app's
primary source. Both PGE and Site Guide AU expose key-less public read APIs
that [the_paragliding_app](https://github.com/Kevin-McIsaac/the_paragliding_app)
already consumes for display, but that does not by itself cover
redistribution. Confirm with each source's maintainers before the app switches
over.

- [ ] PGE — confirmed OK to redistribute derived/merged data
- [ ] Site Guide AU — confirmed OK to redistribute derived/merged data

## Running locally

```bash
pip install -e ".[dev]"
pytest                                    # 45 tests, no network

python -m src.pipeline --dry-run --scope au   # fast: Australia only
python -m src.pipeline --dry-run               # global, ~60s (one big PGE fetch)
python -m src.pipeline                         # writes sites/, review.json, state/
```

`--force` ignores the Site Guide version gate and refetches regardless.

## CI

`.github/workflows/sync.yml` runs weekly and on manual dispatch, opening a PR
only when something changed. A source whose record count drops more than 20%
run-over-run aborts the whole run rather than proposing to delete a country.
