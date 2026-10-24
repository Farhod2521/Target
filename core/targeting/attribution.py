"""How long after seeing an advert a result still belongs to it."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class AttributionWindow:
    """One way of deciding which advert a result belongs to."""

    provider: str
    key: str
    click_days: int
    view_days: int
    provider_label: str


WINDOWS: Final[tuple[AttributionWindow, ...]] = (
    AttributionWindow("meta", "click_7_view_1", 7, 1, "7-day click, 1-day view"),
    AttributionWindow("meta", "click_7", 7, 0, "7-day click"),
    AttributionWindow("meta", "click_1_view_1", 1, 1, "1-day click, 1-day view"),
    AttributionWindow("meta", "click_1", 1, 0, "1-day click"),
)

ATTRIBUTION_GOALS: Final[frozenset[str]] = frozenset({"OFFSITE_CONVERSIONS"})


def takes_attribution(optimization_goal: str) -> bool:
    """Whether a window may be sent beside this optimisation goal."""
    return optimization_goal.strip().upper() in ATTRIBUTION_GOALS


_BY_KEY: Final[dict[tuple[str, str], AttributionWindow]] = {
    (row.provider, row.key): row for row in WINDOWS
}

_BY_PROVIDER: Final[dict[str, tuple[AttributionWindow, ...]]] = {}
for _row in WINDOWS:
    _BY_PROVIDER[_row.provider] = (*_BY_PROVIDER.get(_row.provider, ()), _row)


def windows_for(*, provider: str) -> tuple[AttributionWindow, ...]:
    """Every window this provider offers, its own default first."""
    return _BY_PROVIDER.get(provider, ())


def attribution_window(*, provider: str, key: str) -> AttributionWindow | None:
    """The named window, or ``None`` for one the provider has no shape for."""
    return _BY_KEY.get((provider, key))


__all__ = [
    "ATTRIBUTION_GOALS",
    "WINDOWS",
    "AttributionWindow",
    "attribution_window",
    "takes_attribution",
    "windows_for",
]
