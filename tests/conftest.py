from src.model import SiteRecord


def record(provider="pge", id="1", **overrides):
    defaults = dict(
        provider=provider,
        id=id,
        name="Bald Hill",
        role="launch",
        lat=-33.7,
        lon=151.3,
        altitude=200.0,
        country="AU",
        orientation=frozenset({"N", "NE"}),
    )
    return SiteRecord(**{**defaults, **overrides})
