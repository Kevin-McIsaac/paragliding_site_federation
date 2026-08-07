# Paragliding Site Federation

Cross-references national paragliding site guides against
[ParaglidingEarth](https://www.paraglidingearth.com) (PGE) and proposes the
resulting links as reviewed pull requests — never written directly into PGE
or any other guide.

## Why

PGE is global and community-maintained, but several countries run their own
better-curated guides. This project links those guides to their PGE
counterparts so the connections are visible and, eventually, could be
proposed back to PGE's maintainers for the whole community's benefit. v1
covers exactly two sources — PGE and [Site Guide AU](https://siteguide.org.au)
— scoped to Australia, since that's the only region both currently cover.
Other national guides (DHV, FFVL, Flyland, BHPA) are follow-on work once each
is confirmed to expose usable public data; none have been checked yet.

## How it works

A scheduled GitHub Action re-fetches both sources, matches sites, and opens a
single pull request per run summarizing what changed. Merging the PR is the
actual publish step — nothing is written anywhere until a human approves it.

### Matching

Two records are compared only if they're the same role (launch/landing) and
within 750m of each other — beyond that they're never even scored. An
explicit cross-reference already present in either record (an ID or URL
pointing at the other) short-circuits straight to a confirmed match,
bypassing the role gate. Otherwise, four signals combine into a 0–1
confidence score:

| Signal | Weight | Notes |
|---|---|---|
| Distance | 0.45 | Linear decay to 0 at 500m |
| Wind orientation overlap | 0.25 | Neutral (0.5) if either side lacks the data |
| Name similarity | 0.20 | Fuzzy match; neutral if a name is missing |
| Altitude difference | 0.10 | Neutral if either side lacks the data |

Minus 0.15 if the two records report different countries. Many-candidates
per site are resolved to a clean 1:1 assignment greedily (highest score
claims first) — but only within the linkable bands; low-confidence
candidates aren't mutually exclusive, since they're not assertions of truth.

**Bands**: ≥0.80 auto-linked · 0.55–0.80 auto-linked but flagged for review ·
0.30–0.55 recorded as a candidate, not linked · below 0.30 discarded
entirely.

### File format

One link = one file: `links/<pge_id>__<source>-<source_id>.json`, containing
the two sides' identity, the match status/confidence/component breakdown,
and `last_changed_run` (only bumped when content actually changes, so an
unrelated run's diff stays clean). Candidates live in `links/candidates/`.

Rejecting a match is a **tombstone**, not a deletion — set
`"status": "rejected"` with a `"rejected_reason"` and leave the file in
place. The pipeline skips any pair with an existing rejected tombstone, so a
declined match doesn't reappear on the next run. Promoting a candidate means
moving its file into `links/` with `"status": "manual_linked"`.

Source sites with no PGE candidate at all (nothing survives the gates) go to
`unmatched/current.jsonl` — a plain worklist, not per-file, since there's
nothing to review-and-decide yet. It's the seed list for eventually
proposing genuinely new PGE sites.

## Licensing — must be checked before enabling real runs

Both PGE and Site Guide AU expose key-less public read APIs that
[the_paragliding_app](https://github.com/Kevin-McIsaac/the_paragliding_app)
already consumes for on-screen display. That does not automatically cover republishing *derived* link data
in a public repo, or eventually proposing it back to PGE. **Confirm this with
each source's maintainers before merging the first real PR** — this is a
manual/outreach task, not something resolvable by reading a terms page.

- [ ] PGE — confirmed OK to cross-reference and publish derived links
- [ ] Site Guide AU — confirmed OK to cross-reference and publish derived links

## Running locally

```bash
pip install -e ".[dev]"
pytest                        # unit tests, no network required

python -m src.pipeline --dry-run   # fetch + match against the real APIs, write nothing
python -m src.pipeline             # writes links/, unmatched/, state/, and .pr/ (for CI)
```

## CI

`.github/workflows/sync.yml` runs the pipeline weekly (and on manual
dispatch), opens a PR from `.pr/title.txt` and `.pr/body.md` if
`.pr/has_changes.txt` says `true`, and skips the PR step entirely otherwise.
