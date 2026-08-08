# Unmerged near-misses

- **89** merged automatically (within 250 m)
- **19** left unmerged but close, listed below

Nothing here needs action — this is a report, not a worklist. A run of
true matches just past 250 m would mean the threshold is wrong for this
region; that is what to watch for. To stop a specific pair being merged,
add it to `rejections.json`.

**Why** explains a pair closer than the threshold that still did not
merge — usually because the other side had a nearer match, which points
at a duplicate inside that source (see `DUPLICATES.md`).

Names link to their source page. Name match is context only — it plays
no part in merging, and a low score is the part worth a look.

To change a decision, copy the whole **Override** cell and paste it inside the array in `overrides.json` — no editing needed beyond a reason. `never` keeps a pair apart, `always` forces it together regardless of distance.

| PGE Name | AU Name | Distance | Name match | Why | Override (to merge) |
|---|---|---:|---:|---|---|
| [Lake St Clair](https://www.paraglidingearth.com/?site=10714) | [Glennies Ridge - Lake St Clair (Little Europe)](https://siteguide.org.au/sites/details/109) | 100 m | 100% | counterpart already merged | `{"a": "pge:10714", "b": "siteguide_au:109-238", "verdict": "always", "reason": ""}` |
| [Gordon](https://www.paraglidingearth.com/?site=22859) | [Gordon - South launch](https://siteguide.org.au/sites/details/187) | 162 m | 100% | counterpart already merged | `{"a": "pge:22859", "b": "siteguide_au:187-59", "verdict": "always", "reason": ""}` |
| [Manilla, Mt Borah (NSW)](https://www.paraglidingearth.com/?site=4632) | [Manilla - Mt Borah - South launch](https://siteguide.org.au/sites/details/136) | 167 m | 63% | counterpart already merged | `{"a": "pge:4632", "b": "siteguide_au:136-22", "verdict": "always", "reason": ""}` |
| [Sand Patch](https://www.paraglidingearth.com/?site=11906) | [Sand Patch - Sandpatch](https://siteguide.org.au/sites/details/233) | 184 m | 100% | counterpart already merged | `{"a": "pge:11906", "b": "siteguide_au:233-269", "verdict": "always", "reason": ""}` |
| [Stanwell Park](https://www.paraglidingearth.com/?site=4648) | [Stanwell Park - Bald Hill - East Launch](https://siteguide.org.au/sites/details/132) | 218 m | 100% | counterpart already merged | `{"a": "pge:4648", "b": "siteguide_au:132-113", "verdict": "always", "reason": ""}` |
| [Blackheath](https://www.paraglidingearth.com/?site=11487) | [Mt Blackheath - North ramp](https://siteguide.org.au/sites/details/138) | 219 m | 100% | counterpart already merged | `{"a": "pge:11487", "b": "siteguide_au:138-251", "verdict": "always", "reason": ""}` |
| [Manilla, Mt Borah (NSW)](https://www.paraglidingearth.com/?site=4632) | [Manilla - Mt Borah - East launch](https://siteguide.org.au/sites/details/136) | 253 m | 64% | beyond merge threshold | `{"a": "pge:4632", "b": "siteguide_au:136-21", "verdict": "always", "reason": ""}` |
| [Mt Cambewarra](https://www.paraglidingearth.com/?site=12158) | [Cambewarra](https://siteguide.org.au/sites/details/135) | 273 m | 100% | beyond merge threshold | `{"a": "pge:12158", "b": "siteguide_au:135-183", "verdict": "always", "reason": ""}` |
| [Shoreham](https://www.paraglidingearth.com/?site=15405) | [Shoreham](https://siteguide.org.au/sites/details/179) | 274 m | 100% | beyond merge threshold | `{"a": "pge:15405", "b": "siteguide_au:179-100", "verdict": "always", "reason": ""}` |
| [Canberra, Pig Hill](https://www.paraglidingearth.com/?site=4638) | [Pig Hill](https://siteguide.org.au/sites/details/105) | 284 m | 100% | beyond merge threshold | `{"a": "pge:4638", "b": "siteguide_au:105-27", "verdict": "always", "reason": ""}` |
| [Greenhills - Penny's Tow Paddock, near York](https://www.paraglidingearth.com/?site=4658) | [York - Greenhills Towing - Penny's (Closed)](https://siteguide.org.au/sites/details/89) | 286 m | 76% | beyond merge threshold | `{"a": "pge:4658", "b": "siteguide_au:89-169", "verdict": "always", "reason": ""}` |
| [Rainbow Beach](https://www.paraglidingearth.com/?site=4649) | [Rainbow Beach - Carlo Sand Blow](https://siteguide.org.au/sites/details/11) | 287 m | 100% | beyond merge threshold | `{"a": "pge:4649", "b": "siteguide_au:11-9", "verdict": "always", "reason": ""}` |
| [Warriewood](https://www.paraglidingearth.com/?site=14223) | [Turimetta](https://siteguide.org.au/sites/details/128) | 331 m | 32% | beyond merge threshold | `{"a": "pge:14223", "b": "siteguide_au:128-33", "verdict": "always", "reason": ""}` |
| [Possum Shoot](https://www.paraglidingearth.com/?site=11944) | [Possums - Private Property - All pilots must be inducted and 'check-in' prior to entry. No Parking at Launch.](https://siteguide.org.au/sites/details/257) | 332 m | 17% | beyond merge threshold | `{"a": "pge:11944", "b": "siteguide_au:257-281", "verdict": "always", "reason": ""}` |
| [MURRELLS BEACH](https://www.paraglidingearth.com/?site=14193) | [Portland - Murrells Beach](https://siteguide.org.au/sites/details/158) | 341 m | 15% | beyond merge threshold | `{"a": "pge:14193", "b": "siteguide_au:158-89", "verdict": "always", "reason": ""}` |
| [NE Heaton](https://www.paraglidingearth.com/?site=13404) | [West Heaton Lookout](https://siteguide.org.au/sites/details/264) | 370 m | 80% | beyond merge threshold | `{"a": "pge:13404", "b": "siteguide_au:264-296", "verdict": "always", "reason": ""}` |
| [Long Reef Northfacing](https://www.paraglidingearth.com/?site=21219) | [Long Reef NE](https://siteguide.org.au/sites/details/129) | 386 m | 86% | beyond merge threshold | `{"a": "pge:21219", "b": "siteguide_au:129-34", "verdict": "always", "reason": ""}` |
| [Mona Vale](https://www.paraglidingearth.com/?site=18871) | [Mona Vale](https://siteguide.org.au/sites/details/125) | 387 m | 100% | beyond merge threshold | `{"a": "pge:18871", "b": "siteguide_au:125-30", "verdict": "always", "reason": ""}` |
| [Cairns Bay](https://www.paraglidingearth.com/?site=14653) | [Cairns Bay](https://siteguide.org.au/sites/details/163) | 389 m | 100% | beyond merge threshold | `{"a": "pge:14653", "b": "siteguide_au:163-44", "verdict": "always", "reason": ""}` |
