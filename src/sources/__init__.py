"""The adapters a run fetches from, in the order they are fetched.

Adding a guide is: write the adapter, add it here, rank it in
`model.KEY_PRECEDENCE`, and say where it is authoritative in
`selection.NATIONAL_SCOPE`. The last two stay hand-written on purpose - which
guide keys a launch and which guide wins its content are separate decisions,
and both should be made by a person rather than fall out of the order of this
tuple.

The pipeline asserts every name here is ranked in `KEY_PRECEDENCE` before it
fetches anything, so a guide added without that decision fails the run instead
of being keyed by a `sorted()` tie-break nobody chose.
"""

from __future__ import annotations

from src.sources.pge import PgeSource
from src.sources.siteguide_au import SiteGuideAuSource

ADAPTERS = (PgeSource, SiteGuideAuSource)

__all__ = ["ADAPTERS", "PgeSource", "SiteGuideAuSource"]
