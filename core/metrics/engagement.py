"""What a creative did with the attention it was given."""

from dataclasses import dataclass

from adskit import MinorUnits

from core.metrics import formulas
from core.metrics.arithmetic import basis_points, share, whole_number


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
    return whole_number(formulas.ctr(figures.inline_link_clicks, figures.impressions))


def unique_ctr(figures: EngagementFigures) -> int:
    """What share of the people reached clicked at all."""
    return whole_number(formulas.unique_ctr(figures.unique_clicks, figures.reach))


def frequency(figures: EngagementFigures) -> int:
    """How many times the average person reached was shown the ad."""
    return basis_points(formulas.frequency(figures.impressions, figures.reach))


def click_quality(figures: EngagementFigures) -> int:
    """What share of the clicks came from different people."""
    return whole_number(formulas.click_quality(figures.unique_clicks, figures.clicks))


def hook_rate(figures: EngagementFigures) -> int:
    """What share of the people shown the video watched three seconds of it."""
    return whole_number(formulas.hook_rate(figures.video_views_3s, figures.impressions))


def hold_rate(figures: EngagementFigures) -> int:
    """What share of the people past the first three seconds stayed to the end."""
    return whole_number(
        formulas.hold_rate(figures.video_thruplays, figures.video_views_3s)
    )


def completion_rate(figures: EngagementFigures) -> int:
    """What share watched the whole thing, to the last frame."""
    return whole_number(
        formulas.completion_rate(figures.video_p100, figures.video_plays)
    )


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
    return basis_points(formulas.roas(figures.lead_value_minor, figures.spend_minor))
