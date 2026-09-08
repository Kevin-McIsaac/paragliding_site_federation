"""Write app/site_weather_stations.csv: each ANSG launch with its nearest
Weather Underground PWS station, matched offline from a persistent cache.

The only quota-spending step is discovery (v3/location/near, 1500/day and
30/minute on the key, shared with the app's map layer). Probes happen only
where the cache cannot already answer within the 2 km tier-2 radius, the
cache is checkpointed after every probe, and re-runs probe nothing.

    WUNDERGROUND_API_KEY=... python -m scripts.wu_pws_stations
    python -m scripts.wu_pws_stations --cache-only   # offline, cache as-is
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.pws import OUTPUT_PATH, SITES_PATH, CACHE_PATH, load_sites, run


def http_transport(url: str, params: dict, api_key: str) -> dict:
    """The real transport. Kept this thin so tests never touch the network.

    HTTP 404 means the geocode has no stations in range - an answer, not an
    error, so it comes back as an empty response and the caller records the
    empty probe. 429 is the shared key's rate/quota signal: back off well
    past the 30/minute window and retry, then fail loudly.
    """
    params = {**params, "apiKey": api_key}
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(full_url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {"location": {"stationId": []}}
            if error.code == 429 and attempt < 2:
                time.sleep(60 * (attempt + 1))
                continue
            raise  # the original error, loud, after the back-offs are spent
    raise RuntimeError(f"giving up on {url} after repeated 429s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=CACHE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--sites", type=Path, default=SITES_PATH)
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="match offline against the cache; never probe, never need a key",
    )
    parser.add_argument(
        "--sources",
        default="ansg",
        help="comma list: 'ansg' (the national guide), 'pge-au' (PGE's "
        "Australian rows). 'pge-au' adds ~312 sites, most of them already "
        "cache-covered by the ANSG probes",
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    prefixes, countries = [], None
    for source in sources:
        if source == "ansg":
            prefixes.append("ansg:")
        elif source == "pge-au":
            prefixes.append("pge:")
            countries = frozenset({"au"})  # PGE is worldwide; scope to AU
        else:
            parser.error(f"unknown source '{source}' (use ansg, pge-au)")

    def loader(sites_path):
        return load_sites(sites_path, prefixes=tuple(prefixes), countries=countries)

    api_key = os.environ.get("WUNDERGROUND_API_KEY")
    if not args.cache_only and not api_key:
        parser.error("WUNDERGROUND_API_KEY is not set (or use --cache-only)")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = run(
        transport=http_transport,
        api_key=api_key,
        cache_path=args.cache,
        output_path=args.output,
        sites_path=args.sites,
        loader=loader,
        cache_only=args.cache_only,
        generated_utc=generated,
    )
    print(
        f"{stats.sites} sites ({'+'.join(sources)}): "
        f"{stats.matched_on_site} on-site (<=200 m), "
        f"{stats.matched_nearby} nearby (<=2 km), {stats.unmatched} unmatched; "
        f"{stats.probes} probes this run -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
