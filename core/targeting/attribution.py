"""How long after seeing an advert a result still belongs to it.

Every figure this product shows rests on this and nobody is ever asked
about it: a lead counted today may have been a tap seven days ago, and
narrowing the window moves the same lead from one advert's column to
nobody's. That is the whole reason the choice sits in the advanced tab and
starts as "the provider decides" - somebody who changes it is changing
what *their next campaign's* numbers mean, and they should mean to.

**Only the pairings the provider's own screen offers.** Its documentation
does not say which optimisation goals accept which window, and it refuses
the pairing at creation naming the field - so an invented combination is a
launch that fails on its fourth call.

Provider vocabulary in ``provider_label``; the keys are ours, because the
provider spells this as a nested list rather than as a name.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class AttributionWindow:
    """One way of deciding which advert a result belongs to."""

    provider: str
    # Ours, and unique. Stored on a launch, so it must not be a spelling of
    # the provider's own nested shape.
    key: str
    # How many days after a tap, and after a view, a result still counts.
    # A view window of zero means views are not counted at all, which is
    # what two of the four say.
    click_days: int
    view_days: int
    provider_label: str


WINDOWS: Final[tuple[AttributionWindow, ...]] = (
    # The provider's own default, and the one every campaign built before
    # this question existed delivered against.
    AttributionWindow("meta", "click_7_view_1", 7, 1, "7-day click, 1-day view"),
    AttributionWindow("meta", "click_7", 7, 0, "7-day click"),
    AttributionWindow("meta", "click_1_view_1", 1, 1, "1-day click, 1-day view"),
    AttributionWindow("meta", "click_1", 1, 0, "1-day click"),
)

# Goals the window means anything for. Meta uses it to decide which
# conversion an ad set is optimised and counted on - an event reported by a
# tag on the advertiser's site. A form, a chat or a visit is counted by
# Meta itself, and the field beside one is not a question it answers.
ATTRIBUTION_GOALS: Final[frozenset[str]] = frozenset({"OFFSITE_CONVERSIONS"})


def takes_attribution(optimization_goal: str) -> bool:
    """Whether a window may be sent beside this optimisation goal."""
    return optimization_goal.strip().upper() in ATTRIBUTION_GOALS


_BY_KEY: Final[dict[tuple[str, str], AttributionWindow]] = {
    (row.provider, row.key): row for row in WINDOWS
}

# Indexed rather than filtered, like every other table in this package: a
# lookup keyed by provider leaves no name to compare against.
_BY_PROVIDER: Final[dict[str, tuple[AttributionWindow, ...]]] = {}
for _row in WINDOWS:
    _BY_PROVIDER[_row.provider] = (*_BY_PROVIDER.get(_row.provider, ()), _row)


def windows_for(*, provider: str) -> tuple[AttributionWindow, ...]:
    """Every window this provider offers, its own default first."""
    return _BY_PROVIDER.get(provider, ())


def attribution_window(*, provider: str, key: str) -> AttributionWindow | None:
    """The named window, or ``None`` for one the provider has no shape for.

    ``None`` rather than a fallback: an unknown name has to mean "say
    nothing and let the provider use its own", because the alternative is
    an ad set measured on a window nobody chose.
    """
    return _BY_KEY.get((provider, key))


__all__ = [
    "ATTRIBUTION_GOALS",
    "WINDOWS",
    "AttributionWindow",
    "attribution_window",
    "takes_attribution",
    "windows_for",
]
