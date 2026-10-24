from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from adskit import MinorUnits

from app.common.money import format_minor
from app.modules.metrics.constants import TOP_CAMPAIGNS
from app.modules.metrics.selectors import chart
from app.modules.metrics.selectors.results import OTHER_NOTE, uncounted_label, words_for
from app.modules.metrics.selectors.shapes import (
    CampaignRow,
    FunnelStep,
    KindView,
    Kpi,
    OutcomeBlock,
    Period,
    Series,
)
from core.metrics import (
    LEAD_RUNGS,
    DayFigures,
    Outcome,
    Totals,
    cost_per,
    daily_rate,
    funnel,
    movement,
    total,
)

FUNNEL_TEXT: dict[str, tuple[Any, Any]] = {
    "shown": ("Ko'rsatildi", "Reklamangiz necha marta ekranga chiqdi."),
    "clicked": ("Havolaga o'tdi", "Reklama yuboradigan joyga haqiqatan o'tganlar."),
    "submitted": ("Murojaat qoldirdi", "Formani to'ldirganlar."),
    "site_submitted": (
        "Murojaat qoldirdi",
        "Saytingizdagi formani to'ldirganlar - Meta hisobi bo'yicha.",
    ),
    "qualified": ("Sifatli chiqdi", "Siz sifatli deb belgilaganlar."),
    "chatted": ("Suhbat boshladi", "Reklamadan keyin sizga yozganlar."),
    "called": ("Qo'ng'iroq qildi", "Reklamadagi raqamga qo'ng'iroq qilganlar."),
    "visited": ("Profilga o'tdi", "Reklamani bosib Instagram profilingizga o'tganlar."),
}
RUNGS: dict[Outcome, tuple[tuple[str, str], ...]] = {
    "lead": LEAD_RUNGS,
    "chat": (("shown", "impressions"), ("chatted", "results")),
    "call": (("shown", "impressions"), ("called", "results")),
    "click": (("shown", "impressions"), ("clicked", "results")),
    "site_lead": (
        ("shown", "impressions"),
        ("clicked", "link_clicks"),
        ("site_submitted", "leads_reported"),
    ),
    "profile": (("shown", "impressions"), ("visited", "profile_visits")),
    "view": (),
    "recall": (),
    "none": (),
}


@dataclass(frozen=True, slots=True)
class _Figure:
    key: str
    label: Any
    hint: Any
    lower_is_better: bool
    value: Callable[[Totals], float | None]
    display: Callable[[Totals, str], str]


def money(amount: int | None, currency: str) -> str:
    return (
        format_minor(amount_minor=amount, currency=currency)
        if amount is not None
        else "—"
    )


FIGURES: tuple[_Figure, ...] = (
    _Figure(
        key="spend",
        label="Sarflandi",
        hint="Reklama uchun to'langan pul.",
        lower_is_better=False,
        value=lambda t: t.spend_minor,
        display=lambda t, c: format_minor(amount_minor=t.spend_minor, currency=c),
    ),
)


def headline(*, now: Totals, before: Totals, currency: str) -> tuple[Kpi, ...]:
    return tuple(
        (
            Kpi(
                key=figure.key,
                label=figure.label,
                display=figure.display(now, currency),
                delta_pct=moved.percent,
                trend=moved.direction,
                is_good=moved.is_good,
                hint=figure.hint,
            )
            for figure, moved in (
                (
                    figure,
                    movement(
                        now=figure.value(now),
                        before=figure.value(before),
                        lower_is_better=figure.lower_is_better,
                    ),
                )
                for figure in FIGURES
            )
        )
    )


def lines(
    *,
    days: Sequence[DayFigures],
    currency: str,
    kind: Outcome = "lead",
    known: int | None = None,
) -> tuple[Series, ...]:
    labels = [day.day.strftime("%d.%m") for day in days]
    spend_line = chart.series(
        key="spend",
        label="Sarf",
        values=[day.spend_minor for day in days],
        labels=labels,
        displays=[
            format_minor(amount_minor=day.spend_minor, currency=currency)
            for day in days
        ],
        known=known,
    )
    text = words_for(kind)
    if not text.field:
        return (spend_line,)
    costs = daily_rate(days, field=text.field, per=text.per)
    counts = [int(getattr(day, text.field)) for day in days]
    return (
        chart.series(
            key="count",
            label=text.label,
            values=counts,
            labels=labels,
            displays=[str(count) for count in counts],
            known=None if kind == "lead" else known,
        ),
        chart.series(
            key="cost",
            label=text.cost_label,
            values=costs,
            labels=labels,
            displays=[money(cost, currency) for cost in costs],
            known=known,
        ),
        spend_line,
    )


def steps(totals: Totals, *, kind: Outcome = "lead") -> tuple[FunnelStep, ...]:
    def grouped(n):
        return f"{n:,}".replace(",", " ")

    rungs = RUNGS.get(kind, ())
    if not rungs:
        return ()
    return tuple(
        (
            FunnelStep(
                label=FUNNEL_TEXT[name][0],
                value=grouped(value),
                share_pct=pct,
                note=FUNNEL_TEXT[name][1],
            )
            for name, value, pct in funnel(totals, rungs=rungs)
        )
    )


@dataclass(frozen=True, slots=True)
class CampaignMeta:
    name: str
    delivery: str
    delivery_label: Any
    note: Any = ""
    result: tuple[str, Any] | None = None
    kind: Outcome = "none"
    goal: str = ""


def screen_kind(meta: CampaignMeta | None) -> Outcome:
    if meta is None or not meta.goal.strip():
        return "lead"
    return meta.kind


def _unknown(key: str) -> CampaignMeta:
    return CampaignMeta(name=key, delivery="unknown", delivery_label="Noma'lum")


def campaigns(
    *,
    facts: dict[str, Any],
    leads: dict[str, tuple[int, int]],
    names: dict[str, CampaignMeta],
    currency: str,
) -> tuple[CampaignRow, ...]:
    keys = set(facts) | set(leads)
    rows = []
    for key in keys:
        sums = facts.get(key)
        spend = sums.spend_minor if sums else 0
        count, qualified = leads.get(key, (0, 0))
        meta = names.get(key) or _unknown(key)
        results, result_label, result_cost_label, per = _result_of(meta, sums)
        kind = screen_kind(names.get(key))
        uncounted = kind == "none"
        rows.append(
            CampaignRow(
                name=meta.name,
                delivery=meta.delivery,
                delivery_label=meta.delivery_label,
                spend=format_minor(amount_minor=spend, currency=currency),
                spend_minor=spend,
                leads=count,
                qualified=qualified,
                cpl=money(cost_per(MinorUnits(spend), count), currency),
                cpql=money(cost_per(MinorUnits(spend), qualified), currency),
                note=meta.note or (OTHER_NOTE if uncounted else ""),
                results=results,
                result_label=result_label,
                result_cost=money(cost_per(MinorUnits(spend * per), results), currency),
                result_cost_label=result_cost_label,
                result_source=words_for(meta.kind).source_note if meta.result else "",
                kind=kind,
                uncounted_label=uncounted_label(meta.goal) if uncounted else "",
            )
        )
    rows.sort(key=lambda row: (-row.qualified, -row.leads, -row.spend_minor, row.name))
    return tuple(rows)


def _result_of(meta: CampaignMeta, sums: Any) -> tuple[int, Any, Any, int]:
    if meta.result is None or sums is None:
        return (0, "", "", 1)
    field, word = meta.result
    text = words_for(meta.kind)
    return (getattr(sums, field, 0), word, text.cost_label, text.per)


def view(
    *,
    kind: Outcome,
    label: Any,
    days: Sequence[DayFigures],
    currency: str,
    known: int | None = None,
) -> KindView:
    return KindView(
        kind=kind,
        label=label,
        series=lines(days=days, currency=currency, kind=kind, known=known),
        funnel=steps(total(days), kind=kind),
    )


def build(
    *,
    key: str,
    label: Any,
    days: Sequence[DayFigures],
    before: Sequence[DayFigures],
    currency: str,
    rows: tuple[CampaignRow, ...],
    blocks: tuple[OutcomeBlock, ...] = (),
    views: tuple[KindView, ...] = (),
    scoped_to: Any = "",
    span: int = 1,
    in_progress: bool = False,
    known: int | None = None,
    unknown_after: str = "",
    lead_reported: tuple[int, int] | None = None,
) -> Period:
    now = total(days)
    reported_spend, reported = lead_reported or (now.spend_minor, now.leads_reported)
    kind: Outcome = blocks[0].kind if blocks else "lead"
    views = tuple(
        replace(one, campaigns=sum(1 for row in rows if row.kind == one.kind))
        for one in views
    )
    first = (
        views[0]
        if views
        else view(
            kind=kind,
            label=blocks[0].label if blocks else "",
            days=days,
            currency=currency,
            known=known,
        )
    )
    return Period(
        days=span,
        in_progress=in_progress,
        key=key,
        label=label,
        spend=format_minor(amount_minor=now.spend_minor, currency=currency),
        spend_minor=now.spend_minor,
        shown=f"{now.impressions:,}".replace(",", " "),
        shown_total=now.impressions,
        leads=now.leads,
        qualified=now.qualified,
        cpl=money(now.cpl_minor, currency),
        cpql=money(now.cpql_minor, currency),
        reported_leads=reported,
        reported_cpl=money(cost_per(MinorUnits(reported_spend), reported), currency),
        quality_pct=now.quality_share,
        kpis=headline(now=now, before=total(before), currency=currency),
        outcomes=blocks,
        scoped_to=scoped_to,
        series=first.series,
        funnel=first.funnel,
        views=views,
        unknown_after=unknown_after,
        campaigns=_top(rows),
        campaign_count=len(rows),
    )


def _top(rows: tuple[CampaignRow, ...]) -> tuple[CampaignRow, ...]:
    seen: dict[str, int] = {}
    kept = []
    for row in rows:
        seen[row.kind] = seen.get(row.kind, 0) + 1
        if seen[row.kind] <= TOP_CAMPAIGNS:
            kept.append(row)
    return tuple(kept)
