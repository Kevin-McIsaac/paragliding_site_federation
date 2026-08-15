"""The interface every source adapter implements."""

from __future__ import annotations

from typing import Protocol

from src.model import BoundingBox, SiteRecord


class SourceAdapter(Protocol):
    #: The guide's own abbreviation, lowercased, carried in every `source`
    #: token and so in every ref a device stores. It must appear in
    #: `model.KEY_PRECEDENCE`; the pipeline refuses to run otherwise.
    name: str

    # --- identity, published to the app as `app/guides.json` -----------------
    #
    # The app used to hold all of this in four hand-written `switch` statements
    # plus a second, divergent copy on its About screen, so naming a new guide
    # meant an app release. It is the guide's description of itself, which
    # makes it the producer's to publish. The pipeline refuses to run if an
    # adapter leaves any of it blank, for the same reason it refuses one that
    # is not ranked.

    #: What a pilot sees on a tab, short enough to sit beside two others.
    label: str

    #: The guide spelled out, for the tooltip and the attribution line. A label
    #: alone is ambiguous - "PGE" means nothing until you have seen it once.
    full_name: str

    #: Where the guide lives, for an attribution link. Not the same address as
    #: a site page: DHV's index is `db3/gelaende` and its detail page
    #: `db2/details.php`, and the app needs both.
    homepage: str

    #: One site's page, with `{id}` standing for **the guide's own id in the
    #: row's `site_group`** - not the one in its `source`.
    #:
    #: That distinction is the whole point of publishing a template at all. A
    #: `source` id names the launch, and several guides append a suffix their
    #: own website does not address (`pge:6824-lz`, `ansg:lz-1`,
    #: `dhv:1443-zwoelferkopf-startplatz-3`) because a page exists per *site*,
    #: not per takeoff. `site_group` already carries exactly that id for every
    #: provider on the row - checked over the whole published catalogue, 19,759
    #: of 19,759 - so one template is correct for launches and landings alike.
    #: The app used to chop the source id at the first hyphen instead, which
    #: was wrong on 4,828 of those 19,759 links.
    site_url_template: str

    #: How the guide licenses its data, and where the licence is written.
    #: Blank where the guide publishes no terms - DHV publishes none with its
    #: KML export, and saying nothing is more honest than implying a licence.
    licence: str
    licence_url: str

    #: The extent this guide publishes. The pipeline fetches the overlap of
    #: this and the run's scope, so a national guide is not asked for the
    #: world and a world guide is not asked twice. Declared by the adapter
    #: rather than by the caller: the pipeline used to hard-code
    #: `AUSTRALIA_BBOX` beside the Site Guide fetch, which put one source's
    #: geography in a file that knows nothing about it.
    bbox: BoundingBox

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        """Return every site this source has within bbox."""
        ...
