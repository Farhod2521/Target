"""What a creative did with the attention it was given.

A different question from the one :mod:`core.metrics.derive` answers. That
one is about a period - what it cost, how it moved, where people fell out
of the funnel. This one is about **one object on one day**: whether the ad
held anybody, whether the clicks it earned were real, and whether the money
came back.

Two rules run through it.

**Every figure here is a ratio, so none of them is additive.** A week's link
CTR is its link clicks over its impressions, never the mean of its days.
That is why these take figures rather than a list of them: the caller sums
the counts it may sum, and the ratio is computed once at the end.

**``reach`` and the two ``unique_`` counts count people.** Adding them
across days or across objects counts somebody twice, so anything built on
them - :func:`unique_ctr` above all - is valid for a single row and for a
period only when the provider was asked for that period's reach directly.

Percentages, as whole numbers, like :func:`core.metrics.share`. A ratio
returned as a float would be formatted differently by every caller, and
these are read side by side.
"""

from dataclasses import dataclass

from adskit import MinorUnits

from core.metrics.contracts import share


@dataclass(frozen=True, slots=True)
class EngagementFigures:
    """One object's day, in the counts the ratios below are built from.

    Zeros throughout rather than ``None``. An image ad genuinely had no
    video plays, and a day with no impressions genuinely had no clicks;
    both are counts of nothing rather than answers nobody gave.
    """

    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    unique_clicks: int = 0
    inline_link_clicks: int = 0
    outbound_clicks: int = 0
    video_plays: int = 0
    video_thruplays: int = 0
    video_p100: int = 0
    spend_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType, not a call
    lead_value_minor: MinorUnits = MinorUnits(0)  # noqa: RUF009 - NewType


def link_ctr(figures: EngagementFigures) -> int:
    """Clicks that went where the money was sent, per hundred impressions.

    The honest CTR. The headline one counts every click on the unit -
    expanding the caption, opening the page's profile, tapping the video -
    and an ad can look busy on that number while sending nobody anywhere.
    """
    return share(part=figures.inline_link_clicks, whole=figures.impressions)


def unique_ctr(figures: EngagementFigures) -> int:
    """What share of the people reached clicked at all.

    **One row at a time.** Both halves count people, so a total summed
    across days or ad sets counts anybody who saw two of them twice, and
    the ratio built on that total is wrong in a direction that flatters.
    """
    return share(part=figures.unique_clicks, whole=figures.reach)


def frequency(figures: EngagementFigures) -> int:
    """How many times the average person reached was shown the ad.

    In hundredths, like everything else here: ``240`` is two and a bit
    showings each. Not a percentage of anything - it passes a hundred as soon
    as anybody sees the ad twice, which is normal and is the point of it.

    **The one figure the provider is asked for nowhere and computed here
    instead.** It is exactly impressions over reach, and both are collected;
    asking for the provider's own copy would buy a second version of a
    division that can disagree with ours. That is the same rule the whole
    breakdown request is built on - counts are asked for, ratios are not.

    Where it earns its keep is a placement cut. A story is shown to the same
    person several times as often as a feed is, so the figure differs sharply
    between slices of one ad set, and a slice whose frequency is climbing day
    by day is a creative wearing out in that placement specifically.

    **One row at a time**, and this one cannot be worked around. ``reach``
    counts people, so a range's frequency needs the range's deduplicated
    reach, which no sum of days can produce - a person seen on Monday and
    Tuesday is two rows and one person. A range-wide frequency exists only if
    the provider is asked for the range as a single row, which nothing here
    does.
    """
    return share(part=figures.impressions, whole=figures.reach)


def click_quality(figures: EngagementFigures) -> int:
    """What share of the clicks came from different people.

    A hundred means everybody clicked once. A low number means a handful of
    people kept tapping, which is a crowd of one wearing the budget down -
    and it is invisible from the click count alone.
    """
    return share(part=figures.unique_clicks, whole=figures.clicks)


def hook_rate(figures: EngagementFigures) -> int:
    """What share of the people shown the video started watching it.

    The first second of a creative, measured. A falling hook rate is the
    earliest sign an ad has been seen too often - it shows here before it
    shows in the cost per lead, which is the whole reason for collecting
    video figures at all.

    Meta's own definition of this uses three-second views. That metric was
    removed from the Marketing API and is not available on the current
    version, so this is built on video *starts* instead. It answers the
    same question and is not the same number: it will read higher than a
    three-second rate quoted anywhere else, and the two must not be
    compared with each other.
    """
    return share(part=figures.video_plays, whole=figures.impressions)


def hold_rate(figures: EngagementFigures) -> int:
    """What share of the people who started the video stayed to the end.

    "The end" is the provider's own threshold - watched through, or fifteen
    seconds, whichever comes first. Read beside :func:`hook_rate` rather
    than instead of it: a creative that hooks nobody and holds everybody is
    a different problem from one that does the opposite.
    """
    return share(part=figures.video_thruplays, whole=figures.video_plays)


def completion_rate(figures: EngagementFigures) -> int:
    """What share watched the whole thing, to the last frame."""
    return share(part=figures.video_p100, whole=figures.video_plays)


@dataclass(frozen=True, slots=True)
class WatchPoint:
    """How many of the people who started a video were still there.

    ``at_pct`` is how far through - 25, 50, 75, 100 - and ``share_pct`` is
    the share of the people who *started*, never of the impressions. The
    denominator matters: a video shown ten thousand times and started by
    two hundred has a shape worth reading, and measuring it against the ten
    thousand would flatten every quartile into the same one percent.
    """

    at_pct: int
    share_pct: int


def watch_shape(
    *, plays: int, quartiles: tuple[int, int, int, int]
) -> tuple[WatchPoint, ...]:
    """Where a video loses the people who started it.

    One ratio says a video is or is not held to the end; four say *where*
    it stops being held, and that is the difference between a creative
    worth trimming and one worth replacing. A fall between the first two
    points is an opening that promises the wrong thing; a fall between the
    last two is a video that is simply too long.

    Empty for anything nobody started, which is every image advert. Not a
    row of noughts: an image ad did not lose its audience at the first
    quarter, it never had a video to lose them from, and four empty bars
    say the first thing.

    The quartiles are given in order and are not checked against each
    other. A provider that reports more people at the half than at the
    quarter is reporting something odd, and quietly smoothing it would hide
    exactly the row worth looking at.
    """
    if plays <= 0:
        return ()
    return tuple(
        WatchPoint(at_pct=at, share_pct=share(part=count, whole=plays))
        for at, count in zip((25, 50, 75, 100), quartiles, strict=True)
    )


def value_per_spend(figures: EngagementFigures) -> int | None:
    """What the provider says the leads were worth, per hundred spent.

    ``250`` means the provider valued them at two and a half times their
    cost. ``None`` when nothing was spent, because a return on no spend is
    not infinite - it is a question nobody asked.

    Almost always zero here, and that is not a bug. A value only exists if
    the advertiser sends one back, which lead campaigns rarely do. The
    revenue this product actually reasons about is the sale somebody marks
    by hand, and it does not come from the provider at all.
    """
    if figures.spend_minor <= 0:
        return None
    return share(part=figures.lead_value_minor, whole=figures.spend_minor)
