"""Whether a group has said enough to decide on: the one rule every verdict asks.

**The brief's rule.** Money spent of at least :data:`SPEND_MULTIPLE` times
what one result usually costs here; under it nothing is decided - no stop,
no "dearer", no "it brings nothing", only "wait". A nought on a third of a
result's usual price is a group that has not had its chance yet, and a
price read off one or two results is luck. The stop the agent makes by
itself, the proposal cards, the watch's messages and the night's diagnosis
all ask this, so no surface decides on a group another one calls too young.

**Where nothing says what a result costs** - an account whose first result
of the kind has not come yet - the brief's rule has no yardstick, and the
showings stand in for it: :data:`MIN_IMPRESSIONS` of them and
:data:`MIN_LINK_CLICKS` clicks. Without that a first campaign, the one
nobody else is watching, could never be judged at all.
"""

from typing import Final

# Spend this many results' usual price before anything is decided.
SPEND_MULTIPLE: Final = 3
# With no usual price anywhere: this many showings and clicks instead.
MIN_IMPRESSIONS: Final = 1_000
MIN_LINK_CLICKS: Final = 30


def enough_spent(
    *, spend_minor: int, usual_cost_minor: int | None, per: int = 1
) -> bool:
    """Whether the money gone is the brief's three results' worth.

    ``per`` is how many results ``usual_cost_minor`` is the price of - a
    thousand for showings. ``False`` where there is no usual price.
    """
    if not usual_cost_minor or usual_cost_minor <= 0:
        return False
    return spend_minor * per >= usual_cost_minor * SPEND_MULTIPLE


def enough_to_decide(
    *,
    spend_minor: int,
    usual_cost_minor: int | None,
    impressions: int,
    link_clicks: int,
    per: int = 1,
) -> bool:
    """The brief's rule, or the showings where no usual price exists."""
    if usual_cost_minor:
        return enough_spent(
            spend_minor=spend_minor, usual_cost_minor=usual_cost_minor, per=per
        )
    return impressions >= MIN_IMPRESSIONS and link_clicks >= MIN_LINK_CLICKS


__all__ = [
    "MIN_IMPRESSIONS",
    "MIN_LINK_CLICKS",
    "SPEND_MULTIPLE",
    "enough_spent",
    "enough_to_decide",
]
