from collections.abc import Callable, Iterable, Mapping
from typing import Any

from adskit import MinorUnits

from app.common.money import format_minor
from app.modules.metrics.constants import BreakdownKind
from app.modules.metrics.selectors.periods import CampaignMeta, screen_kind
from app.modules.metrics.selectors.results import words_for
from app.modules.metrics.selectors.shapes import (
    CutTab,
    KindCuts,
    SegmentBlock,
    ShowingRow,
    SourceBar,
)
from core.metrics import cost_per, share

CUT_TABS: dict[str, Any] = {
    BreakdownKind.AGE_GENDER: "Yosh",
    BreakdownKind.PLATFORM_POSITION: "Joylashuv",
    BreakdownKind.REGION: "Hudud",
}
SHOWING_ROWS = 5
Spread = Iterable[tuple[str, str, int, int]]


def kind_cuts(
    *,
    kinds: Iterable[str],
    segments: Iterable[SegmentBlock],
    hours: tuple[SourceBar, ...],
    cities: tuple[SourceBar, ...],
    spread: Mapping[str, list[tuple[str, str, int, int]]],
    names: Mapping[str, CampaignMeta],
    spans: Mapping[str, int],
    currency: str,
    label_of: Callable[[str], str],
) -> tuple[KindCuts, ...]:
    out = []
    for kind in kinds:
        if kind == "lead":
            tabs = _lead_tabs(segments=segments, hours=hours, cities=cities)
        else:
            tabs = tuple(
                CutTab(
                    key=cut, label=CUT_TABS[cut], days=spans.get(cut, 0), showing=rows
                )
                for cut in CUT_TABS
                if (
                    rows := _showing(
                        rows=spread.get(str(cut), []),
                        kind=kind,
                        names=names,
                        currency=currency,
                        label_of=label_of,
                    )
                )
            )
        if tabs:
            out.append(KindCuts(kind=kind, tabs=tabs))
    return tuple(out)


def _lead_tabs(
    *,
    segments: Iterable[SegmentBlock],
    hours: tuple[SourceBar, ...],
    cities: tuple[SourceBar, ...],
) -> tuple[CutTab, ...]:
    tabs = [
        CutTab(key=block.key, label=CUT_TABS[block.key], days=block.days, block=block)
        for block in segments
        if block.days and block.has_forms
    ]
    if cities:
        tabs.append(CutTab(key="city", label="Shahar", bars=cities))
    if hours:
        tabs.append(CutTab(key="hour", label="Soat", bars=hours))
    return tuple(tabs)


def _showing(
    *,
    rows: Spread,
    kind: str,
    names: Mapping[str, CampaignMeta],
    currency: str,
    label_of: Callable[[str], str],
) -> tuple[ShowingRow, ...]:
    summed: dict[str, tuple[int, int]] = {}
    for campaign, value, spend, shown in rows:
        if screen_kind(names.get(campaign)) != kind:
            continue
        was_spend, was_shown = summed.get(value, (0, 0))
        summed[value] = (was_spend + spend, was_shown + shown)
    ranked = sorted(
        ((value, spend, shown) for value, (spend, shown) in summed.items() if spend),
        key=lambda one: (-one[1], one[0]),
    )[:SHOWING_ROWS]
    if not ranked:
        return ()
    top = ranked[0][1]
    per = words_for("view").per if kind == "view" else 0
    return tuple(
        (
            ShowingRow(
                label=label_of(value),
                shown=f"{shown:,}".replace(",", " "),
                spend=format_minor(amount_minor=spend, currency=currency),
                share_pct=share(part=spend, whole=top),
                cost=_per_thousand(
                    spend=spend, shown=shown, per=per, currency=currency
                ),
            )
            for value, spend, shown in ranked
        )
    )


def _per_thousand(*, spend: int, shown: int, per: int, currency: str) -> str:
    if not per:
        return ""
    cost = cost_per(MinorUnits(spend * per), shown)
    return "" if cost is None else format_minor(amount_minor=cost, currency=currency)
