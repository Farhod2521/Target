"""Each object's result, counted in the kind it was bought for."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import func

from app.common.money import format_minor
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.results import screen_kind
from core.chat.rungs import ResultDigest, result_text
from core.metrics.outcomes import Outcome

COUNTED_IN: Final[dict[str, str]] = {
    "chat": "results",
    "call": "results",
    "click": "results",
    "view": "shown",
    "recall": "recallers",
    "profile": "profile_visits",
    "site_lead": "reported",
}

PER: Final[dict[str, int]] = {"view": 1_000}


def figure_sums(model: Any = MetricsDaily) -> list[Any]:
    """The columns every figures line is summed from, as labelled sums."""
    return [
        func.sum(model.spend_minor).label("spend"),
        func.sum(model.impressions).label("shown"),
        func.sum(model.inline_link_clicks).label("link_clicks"),
        func.sum(model.leads_reported).label("reported"),
        func.sum(model.results_reported).label("results"),
        func.sum(model.recallers).label("recallers"),
        func.sum(model.profile_visits).label("profile_visits"),
    ]


@dataclass(frozen=True, slots=True)
class KindSums:
    """One kind of result over some groups: how many, and what they spent."""

    kind: Outcome
    count: int
    spend_minor: int


def kind_of(goal: str, promoted: Mapping[str, Any] | None = None) -> Outcome:
    """What a group with this goal was bought for, as the screens read it."""
    return screen_kind(goal or "", promoted)


def count_of(kind: Outcome, *, figures: Mapping[str, Any], leads: int) -> int | None:
    """How many of its results came, or ``None`` for a kind nothing counts."""
    if kind == "lead":
        return leads
    column = COUNTED_IN.get(kind)
    if column is None:
        return None
    return int(figures.get(column) or 0)


def digest(item: KindSums, *, currency: str) -> ResultDigest:
    """One kind as the context carries it, priced over its own spend."""
    cost = ""
    if item.count > 0:
        each = item.spend_minor * PER.get(item.kind, 1) // item.count
        cost = format_minor(amount_minor=each, currency=currency)
    return ResultDigest(kind=item.kind, count=item.count, cost=cost)


def digests(items: Iterable[KindSums], *, currency: str) -> tuple[ResultDigest, ...]:
    """Every kind, dearest first."""
    ordered = sorted(items, key=lambda item: -item.spend_minor)
    return tuple(digest(item, currency=currency) for item in ordered)


def merged(items: Iterable[KindSums]) -> tuple[KindSums, ...]:
    """The same kinds from several places, each kind summed on its own."""
    found: dict[Outcome, list[int]] = {}
    for item in items:
        row = found.setdefault(item.kind, [0, 0])
        row[0] += item.count
        row[1] += item.spend_minor
    return tuple(
        KindSums(kind=kind, count=count, spend_minor=spend)
        for kind, (count, spend) in found.items()
    )


def group_result(
    *,
    goal: str,
    promoted: Mapping[str, Any] | None = None,
    figures: Mapping[str, Any],
    leads: int,
    currency: str,
) -> str:
    """One group's result line, or empty for a kind nothing counts."""
    kind = kind_of(goal, promoted if isinstance(promoted, Mapping) else None)
    count = count_of(kind, figures=figures, leads=leads)
    if count is None:
        return ""
    spend = int(figures.get("spend") or 0)
    item = KindSums(kind=kind, count=count, spend_minor=spend)
    return result_text(digest(item, currency=currency))


__all__ = [
    "COUNTED_IN",
    "KindSums",
    "count_of",
    "digest",
    "digests",
    "figure_sums",
    "group_result",
    "kind_of",
    "merged",
]
