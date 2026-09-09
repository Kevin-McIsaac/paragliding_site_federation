"""Bureau of Meteorology AWS stations as a second station network.

WU's PWS network lives where people live - backyards in towns - so ridge and
interior launches go unmatched. BOM's automatic weather stations live where
airports are, which is the complement: rural coverage WU structurally cannot
provide. The whole network is fetched as 8 per-state bulk XML files, no key,
refreshing every 10 minutes - the entire Australian station pool costs 8
requests a day (reg.bom.gov.au/fwo/<product>.xml, documented in
the_paragliding_app/docs/api/BOM_WEATHER_STATIONS.md).

The adapter is deliberately the same shape as the WU probe path: parse into
``Station`` records, merge into the shared cache, checkpoint. Matching stays
source-blind - see Cache.nearest.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from src.pws import Cache, Station

#: Per-state bulk observation products. The state letter drives the
#: per-station page URL (IDx60920.xml is the bulk file; IDx60901.<wmo>.shtml
#: the station's own page).
STATE_PRODUCTS = (
    "IDW60920",  # WA
    "IDN60920",  # NSW (incl. ACT)
    "IDV60920",  # VIC
    "IDQ60920",  # QLD
    "IDS60920",  # SA
    "IDT60920",  # TAS
    "IDD60920",  # NT
)

BOM = "bom"
USER_AGENT = "paragliding-site-federation/1.0"


def station_url(product_id: str, wmo_id: str) -> str:
    """The station's own observation page on reg.bom.gov.au."""
    page_product = product_id.replace("60920", "60901")
    return f"http://www.bom.gov.au/products/{page_product}/{page_product}.{wmo_id}.shtml"


def _local(tag: str) -> str:
    """ElementTree keeps namespaces in tags; BOM's product XML may or may not
    carry one depending on schema version. Compare on the local name only."""
    return tag.split("}")[-1]


def _epoch(iso_utc: str | None) -> str | None:
    if not iso_utc:
        return None
    try:
        return str(int(datetime.fromisoformat(iso_utc).timestamp()))
    except ValueError:
        return None


def parse_bom_response(product_id: str, xml_text: str) -> list[Station]:
    """Pull the stations out of one state's bulk file.

    Station coordinates, elevation and observation time are attributes;
    wind elements are children of period/level. A station whose latest
    period carries no wind still enters the pool - coordinates are the
    point, and liveness is judged from the observation timestamp."""
    root = ET.fromstring(xml_text)
    stations = []
    for st in (el for el in root.iter() if _local(el.tag) == "station"):
        wmo = st.get("wmo-id")
        lat, lon = st.get("lat"), st.get("lon")
        if not wmo or not lat or not lon:
            continue
        period = next((el for el in st if _local(el.tag) == "period"), None)
        seen = _epoch(period.get("time-utc")) if period is not None else None
        height = st.get("stn-height")
        stations.append(
            Station(
                station_id=wmo,
                lat=float(lat),
                lon=float(lon),
                update_time_utc=seen,
                network=BOM,
                elevation=float(height) if height not in (None, "") else None,
                url=station_url(product_id, wmo),
            )
        )
    return stations


def refresh(cache: Cache, fetcher) -> int:
    """Fetch every state's bulk file, merge, checkpoint after each.

    ``fetcher(url) -> xml text``; eight calls a day for the whole network,
    so no throttling dance - but each file is checkpointed as it lands,
    same resume property as the WU probe loop."""
    fresh = 0
    for product_id in STATE_PRODUCTS:
        url = f"http://reg.bom.gov.au/fwo/{product_id}.xml"
        try:
            stations = parse_bom_response(product_id, fetcher(url))
        except ET.ParseError:
            continue  # a malformed state file must not sink the other seven
        fresh += cache.merge(stations)
        cache.save()
    return fresh
