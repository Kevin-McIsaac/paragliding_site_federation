from src.model import SiteRecord


def record(provider="pge", id="1", **overrides):
    defaults = dict(
        provider=provider,
        id=id,
        name="Bald Hill",
        role="launch",
        lat=-33.7,
        lon=151.3,
        wind={"N": 1, "NE": 2},
        country="AU",
    )
    return SiteRecord(**{**defaults, **overrides})


# ~1.113m per 0.00001 degrees of latitude, for readable fixtures.
def metres(m):
    return m / 111_320.0
