"""Turning days into the four things a dashboard says.

A total, how it moved, where people fell out of the funnel, and the shape of
the line. Four functions, no clock, no database, no formatting.

One rule decides most of what is here: **a rate is recomputed, never
averaged**. Thirty days of CPQL averaged together is not the month's CPQL -
a day that spent nothing and produced nothing counts as much as the day that
produced everything - and the difference is large enough to change what
somebody does with their budget.
"""

from collections.abc import Iterable, Sequence

from adskit import MinorUnits

from core.metrics.contracts import (
    DayFigures,
    Direction,
    Movement,
    Totals,
    cost_per,
    share,
)


def total(days: Iterable[DayFigures]) -> Totals:
    """Every additive figure summed. Rates are properties of the result.

    Nothing here reads ``reach``: it counts people rather than events, so
    two ad sets that showed the same person an ad both report that person
    and a sum is an overcount the provider would never print. A total reach
    has to be asked for, not added up.
    """
    rows = list(days)
    return Totals(
        spend_minor=MinorUnits(sum(row.spend_minor for row in rows)),
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
        link_clicks=sum(row.link_clicks for row in rows),
        leads=sum(row.leads for row in rows),
        qualified=sum(row.qualified for row in rows),
        leads_reported=sum(row.leads_reported for row in rows),
        results=sum(row.results for row in rows),
        recallers=sum(row.recallers for row in rows),
        profile_visits=sum(row.profile_visits for row in rows),
    )


def movement(
    *, now: float | None, before: float | None, lower_is_better: bool
) -> Movement:
    """How one figure compares with the same figure a period earlier.

    ``None`` on either side means flat and not good. It is what a cost per
    lead is when there were no leads, and inventing a hundred-percent
    improvement out of a period nobody bought anything in is the kind of
    number that gets a budget raised for the wrong reason.

    A first period compares against nothing, which is also flat: an account
    that started last week did not improve infinitely, it started.
    """
    if now is None or before is None or not before:
        return Movement()

    change = (now - before) / before * 100
    percent = round(abs(change))
    if percent == 0:
        return Movement()

    direction: Direction = "up" if change > 0 else "down"
    return Movement(
        percent=percent,
        direction=direction,
        # The half that is not arithmetic. Falling costs and rising counts
        # are both good news, and which one this is the caller's to say.
        is_good=(direction == "down") if lower_is_better else (direction == "up"),
    )


# The ladder a form campaign is read down, and the default because it is
# the one this screen was built around.
#
# ``(name, field)`` pairs: the name is what the screen translates and the
# field is what it reads off the totals. Named rather than hard-coded
# because the ladder is not the same for every kind of campaign - a chat
# campaign's second rung is a conversation, and there is no honest rung
# between an impression and it. See ``apps.metrics.selectors.periods.RUNGS``.
LEAD_RUNGS: tuple[tuple[str, str], ...] = (
    ("shown", "impressions"),
    ("clicked", "link_clicks"),
    ("submitted", "leads"),
    # ("qualified", "qualified"),
)


def funnel(
    totals: Totals, *, rungs: Sequence[tuple[str, str]] = LEAD_RUNGS
) -> tuple[tuple[str, int, int | None], ...]:
    """Each rung as ``(name, value, share of the rung above)``.

    Each share is against the step before it rather than against the top,
    and that is not a presentation choice. "Nought point nought four percent
    of the people who saw it" answers a question nobody has; "one in five of
    the people who opened the form" answers the one they came with.

    **The second step is link clicks and not clicks.** ``clicks`` counts
    every tap on the unit - expanding the caption, opening the page's
    profile, tapping a video - so a creative that is interesting to look at
    scores well on it and sends nobody anywhere. This funnel exists to
    answer "where do people fall out", and a step that counts taps nobody
    intended as a step is the one place that question can be answered
    wrongly without anybody noticing: it inflates the second step, which
    deflates the third, and the conclusion is that the form is the problem
    when the creative was.

    ``None`` where the step above had nothing, and never nought. A share of
    a nought is undefined rather than zero, and it happens in a real case:
    a provider that reported no link clicks for a range that had clicks has
    not said the destination got none, it has said nothing. Printing "0%"
    there would be an answer where there is none. The first step has no
    share for the same reason - there is nothing above it.

    Names rather than sentences: three languages read these, and a step
    called ``"clicked"`` is translated at the screen.

    **There was a fourth step and it is withdrawn**, not lost: the leads
    somebody had marked as worth having. That marking is switched off -
    see ``templates/leads/partials/_live.html`` - so the step would be a
    nought under every funnel on every account, and the last bar of a
    funnel falling to nothing is the one shape that says the advertising
    failed. ``Totals.qualified`` is still computed, so restoring it is
    uncommenting the line in :data:`LEAD_RUNGS`.

    **The ladder is the caller's and the arithmetic is here.** Three fixed
    rungs ending in a lead would put "Murojaat qoldirdi: 0" at the bottom
    of every funnel a chat campaign draws, under a conversation count on
    the same screen. What a campaign's rungs are is a question about what
    it was bought for; what share each is of the one above is arithmetic,
    and only the second belongs down here.
    """
    steps = tuple((name, int(getattr(totals, field))) for name, field in rungs)
    return tuple(
        (name, value, _step_share(steps, index))
        for index, (name, value) in enumerate(steps)
    )


def _step_share(steps: tuple[tuple[str, int], ...], index: int) -> int | None:
    """One step against the one above it, or nothing where there is none."""
    if index == 0:
        return None
    above = steps[index - 1][1]
    return share(part=steps[index][1], whole=above) if above else None


def daily_rate(
    days: Sequence[DayFigures], *, field: str = "leads", per: int = 1
) -> list[int | None]:
    """One cost per day, for plotting. ``None`` where the day had none.

    Kept as ``None`` rather than dropped or zeroed. A day with spend and no
    results is a real day with no answer, and both alternatives lie about
    it: zero draws the line to the floor as though that day were free, and
    dropping the point closes the gap as though the day did not happen.

    The same refusals as the headline figure because it is the same
    function: a chart whose points disappear where the line above it shows
    a number is a chart that disagrees with it.

    ``field`` names what a result is for this campaign, because that is not
    the same column for every one of them - ``leads`` for all of them draws
    a flat empty line on every account that bought anything else.

    ``per`` is a thousand where a single result costs less than the
    smallest unit a currency has. A view does; priced per one it rounds to
    nought and the chart draws the advertising as free.
    """
    return [
        cost_per(MinorUnits(row.spend_minor * per), int(getattr(row, field)))
        for row in days
    ]
