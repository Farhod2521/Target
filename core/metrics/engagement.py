"""What a creative did with the attention it was given."""

from dataclasses import dataclass

from adskit import MinorUnits

from core.metrics.contracts import share


@dataclass(frozen=True, slots=True)
class EngagementFigures:
    """One object's day, in the counts the ratios below are built from."""

    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    unique_clicks: int = 0
    inline_link_clicks: int = 0
    outbound_clicks: int = 0
    video_plays: int = 0
    video_views_3s: int = 0
    video_thruplays: int = 0
    video_p100: int = 0
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    lead_value_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType


def link_ctr(figures: EngagementFigures) -> int:
    """Clicks that went where the money was sent, per hundred impressions."""
    return share(part=figures.inline_link_clicks, whole=figures.impressions)


def unique_ctr(figures: EngagementFigures) -> int:
    """What share of the people reached clicked at all."""
    return share(part=figures.unique_clicks, whole=figures.reach)


def frequency(figures: EngagementFigures) -> int:
    """How many times the average person reached was shown the ad."""
    return share(part=figures.impressions, whole=figures.reach)


def click_quality(figures: EngagementFigures) -> int:
    """What share of the clicks came from different people."""
    return share(part=figures.unique_clicks, whole=figures.clicks)


def hook_rate(figures: EngagementFigures) -> int:
    """What share of the people shown the video watched three seconds of it."""
    return share(part=figures.video_views_3s, whole=figures.impressions)


def hold_rate(figures: EngagementFigures) -> int:
    """What share of the people past the first three seconds stayed to the end."""
    return share(part=figures.video_thruplays, whole=figures.video_views_3s)


def completion_rate(figures: EngagementFigures) -> int:
    """What share watched the whole thing, to the last frame."""
    return share(part=figures.video_p100, whole=figures.video_plays)


@dataclass(frozen=True, slots=True)
class WatchPoint:
    """How many of the people who started a video were still there."""

    at_pct: int
    share_pct: int


def watch_shape(
    *, plays: int, quartiles: tuple[int, int, int, int]
) -> tuple[WatchPoint, ...]:
    """Where a video loses the people who started it."""
    if plays <= 0:
        return ()
    return tuple(
        WatchPoint(at_pct=at, share_pct=share(part=count, whole=plays))
        for at, count in zip((25, 50, 75, 100), quartiles, strict=True)
    )


def value_per_spend(figures: EngagementFigures) -> int | None:
    """What the provider says the leads were worth, per hundred spent."""
    if figures.spend_minor <= 0:
        return None
    return share(part=figures.lead_value_minor, whole=figures.spend_minor)
