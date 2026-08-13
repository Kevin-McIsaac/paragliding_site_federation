"""The interface every source adapter implements."""

from __future__ import annotations

from typing import Protocol

from src.model import BoundingBox, SiteRecord


class SourceAdapter(Protocol):
    #: The guide's own abbreviation, lowercased, carried in every `source`
    #: token and so in every ref a device stores. It must appear in
    #: `model.KEY_PRECEDENCE`; the pipeline refuses to run otherwise.
    name: str

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
