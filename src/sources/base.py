"""The interface every source adapter implements."""

from __future__ import annotations

from typing import Protocol

from src.model import BoundingBox, SiteRecord


class SourceAdapter(Protocol):
    name: str

    def fetch(self, bbox: BoundingBox) -> list[SiteRecord]:
        """Return every site this source has within bbox."""
        ...
