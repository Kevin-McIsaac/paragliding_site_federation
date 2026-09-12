"""Write app/site_weather_stations.csv: each enriched launch with its nearest
weather station, matched offline from a persistent cache.

The only quota-spending step is discovery (v3/location/near, 1500/day and
30/minute on the key, shared with the app's map layer). Probes happen only
where the cache cannot already answer within the 2 km tier-2 radius, the
cache is checkpointed after every probe, and re-runs probe nothing.

    WUNDERGROUND_API_KEY=... python -m scripts.wu_pws_stations
    python -m scripts.wu_pws_stations --cache-only   # offline, cache as-is

Holfuy is a *catalogue*, not a discovery endpoint (see src/holfuy.py). Its
build is a separate, deliberately manual live run; matching against it costs
no Holfuy traffic at all, and its rows stay out of the shipped CSV until
licensing is on file:

    python -m scripts.wu_pws_stations --catalogue-only
    WUNDERGROUND_API_KEY=... python -m scripts.wu_pws_stations \\
        --sources ansg,pge-au --networks wu-pws,bom,holfuy
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

from src import holfuy
from src.bom import USER_AGENT
from src.pws import OUTPUT_PATH, SITES_PATH, CACHE_PATH, Cache, load_sites, run

#: Holfuy rows do not ship until Holfuy's permission is on file, so a
#: Holfuy-inclusive run writes beside the published CSV rather than over it.
#: The publish gate and the weekly sync do not include this name.
HOLFUY_PREVIEW_PATH = OUTPUT_PATH.with_name(
    f"{OUTPUT_PATH.stem}.holfuy-preview{OUTPUT_PATH.suffix}"
)


def resolve_output(requested, networks: tuple[str, ...]):
    """Where the CSV goes, and whether Holfuy rows are in play.

    The licensing gate, in one place: a Holfuy-inclusive run writes beside the
    published CSV rather than over it, unless the caller names a path
    explicitly. The weekly sync and the publish gate do not know the preview
    name, so a preview can never ship by accident.
    """
    preview = "holfuy" in networks
    if requested is not None:
        return Path(requested), preview
    return (HOLFUY_PREVIEW_PATH if preview else OUTPUT_PATH), preview


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
    parser.add_argument("--sites", type=Path, default=SITES_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where the CSV goes. Defaults to the shipped "
        "app/site_weather_stations.csv, or the .holfuy-preview file when "
        "holfuy is in --networks (Holfuy rows do not ship until licensing "
        "is on file)",
    )
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
    parser.add_argument(
        "--networks",
        default="wu-pws",
        help="comma list of station networks the match pool may draw from: "
        "'wu-pws', 'bom' (Bureau AWS, +8 bulk fetches, no key), 'holfuy' (the "
        "catalogue built by --catalogue, no network calls of its own). WU and "
        "BOM stations already cached stay in the pool whether or not this run "
        "fetched them; holfuy enters only when named, because its rows do not "
        "ship until licensing is on file. Matching is source-blind within the "
        "pool: the nearest alive station wins, whatever network",
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=None,
        help="build or refresh the Holfuy catalogue at this path (default "
        f"{holfuy.CATALOGUE_PATH}) before matching. LIVE: ~1,750 sequential "
        "requests paced ~1 s apart, several minutes to half an hour - run it "
        "from a workstation IP by hand, never on CI",
    )
    parser.add_argument(
        "--catalogue-only",
        action="store_true",
        help="build the Holfuy catalogue and stop, without matching",
    )
    parser.add_argument(
        "--refresh-holfuy",
        action="store_true",
        help="re-read every Holfuy station page instead of carrying over the "
        "stations an earlier catalogue already resolved (the default). Use "
        "after Holfuy moves a station or corrects a coordinate",
    )
    parser.add_argument(
        "--holfuy-clock",
        type=float,
        default=holfuy.MIN_REQUEST_INTERVAL_S,
        help="seconds between Holfuy requests, sequential "
        f"(default {holfuy.MIN_REQUEST_INTERVAL_S}); raise it to be kinder, "
        "lower it only for a test",
    )
    args = parser.parse_args()

    # Derived before anything else: it decides where the output goes, because
    # Holfuy rows must not reach the shipped CSV while licensing is unresolved.
    networks = tuple(n.strip() for n in args.networks.split(",") if n.strip())
    output_path, preview = resolve_output(args.output, networks)

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
    if not args.cache_only and not api_key and not args.catalogue_only:
        parser.error("WUNDERGROUND_API_KEY is not set (or use --cache-only)")

    def bom_fetcher(url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")

    if args.catalogue or args.catalogue_only:
        catalogue_path = args.catalogue or holfuy.CATALOGUE_PATH
        holfuy.MIN_REQUEST_INTERVAL_S = args.holfuy_clock
        cache = Cache.load(args.cache)
        catalogue = holfuy.build(
            cache=cache,
            fetcher=holfuy.http_fetcher,
            catalogue_path=catalogue_path,
            on_note=lambda note: print(f"[holfuy] {note}"),
            refresh=args.refresh_holfuy,
        )
        # Emitted from the catalogue already in memory, never re-read from
        # disk: one manual run updates the audit catalogue and the published
        # app file together, and spends no Holfuy traffic on the second.
        app_payload = holfuy.write_app_stations(holfuy.APP_STATIONS_PATH, catalogue)
        print(
            f"{len(catalogue)} Holfuy stations -> {catalogue_path} "
            f"and {args.cache}; "
            f"{len(app_payload['stations'])} published -> "
            f"{holfuy.APP_STATIONS_PATH}"
        )
        if args.catalogue_only:
            return 0

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = run(
        transport=http_transport,
        api_key=api_key,
        cache_path=args.cache,
        output_path=output_path,
        sites_path=args.sites,
        loader=loader,
        cache_only=args.cache_only,
        generated_utc=generated,
        networks=networks,
        bom_fetcher=bom_fetcher if "bom" in networks else None,
    )
    if preview:
        print(
            f"[holfuy] Holfuy rows go to {output_path}, not the shipped CSV, "
            f"until licensing is on file"
        )
    print(
        f"{stats.sites} sites ({'+'.join(sources)}): "
        f"{stats.matched_on_site} on-site (<=200 m), "
        f"{stats.matched_nearby} nearby (<=2 km), {stats.unmatched} unmatched; "
        f"{stats.probes} probes this run -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
