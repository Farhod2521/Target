"""One pair's day or week, added up by goal.

Split from :mod:`app.modules.chat.selectors.daily`, which reads the day once
for every pair; this turns one pair's slice of it into a report.

**A group's own goal, not its campaign's.** Budgets set at the group let one
campaign buy two things, and the goal is what a result is counted by.
"""

from collections.abc import Iterable
from dataclasses import replace
from datetime import date

from app.modules.chat.selectors.day_figures import DayTables
from app.modules.chat.selectors.day_lines import (
    Part,
    against,
    change_text,
    figure_of,
    report_kind,
    report_money,
    result_count,
)
from app.modules.chat.selectors.day_tables import DayPairs
from app.modules.metrics.selectors.results import screen_kind
from core.chat.daily import OFF_STATES
from core.chat.day_report import DailyReport


def pair_report(
    *,
    tables: DayTables,
    day: date,
    day_text: str,
    ongoing: bool,
    currency: str,
    pair: str,
    pairs: DayPairs,
    adset_ids: list[str],
    other_currency: tuple[str, ...],
    describes_elsewhere: bool,
    open_proposals: int = 0,
) -> DailyReport:
    """One pair's period: every group that spent or brought, by goal."""
    shown = [adset_id for adset_id in adset_ids if _did_something(tables, adset_id)]
    here = [
        adset_id for adset_id in shown if _campaign(tables, adset_id) in tables.built
    ]
    elsewhere = [adset_id for adset_id in shown if adset_id not in set(here)]
    here_minor, elsewhere_minor = _money(tables, here), _money(tables, elsewhere)
    figure = figure_of(
        parts=_parts(tables, shown if describes_elsewhere else here),
        currency=currency,
    )
    if not describes_elsewhere:
        figure = replace(
            figure,
            spend=report_money(here_minor + elsewhere_minor, currency),
            spend_minor=here_minor + elsewhere_minor,
        )
    before_minor = sum(
        tables.before.get(adset_id, {}).get("spend", 0) for adset_id in adset_ids
    )
    if not ongoing:
        counted = [
            adset_id
            for adset_id in adset_ids
            if describes_elsewhere or _campaign(tables, adset_id) in tables.built
        ]
        figure = against(
            figure,
            before=figure_of(parts=_before_parts(tables, counted), currency=currency),
        )
    return DailyReport(
        day=day,
        day_text=day_text,
        currency=currency,
        pair=pair,
        page=pairs.names.get(pair, ""),
        page_id=pairs.pages.get(pair, ""),
        account=pairs.accounts.get(pair, ""),
        account_id=pairs.account_ids.get(pair, ""),
        figure=figure,
        ongoing=ongoing,
        here=_text(here_minor, currency),
        elsewhere=_text(elsewhere_minor, currency),
        elsewhere_apart=not describes_elsewhere and elsewhere_minor > 0,
        before="" if ongoing else _text(before_minor, currency),
        before_minor=0 if ongoing else before_minor,
        change="" if ongoing else change_text(figure.spend_minor, before_minor),
        idle=_idle(tables, adset_ids) if describes_elsewhere else 0,
        open_proposals=open_proposals,
        other_currency=other_currency,
    )


def _idle(tables: DayTables, adset_ids: Iterable[str]) -> int:
    """Ads Manager's campaigns on this pair still switched on, that spent
    lately and not that day. One that went silent weeks ago is not news, and
    a pair can hold hundreds."""
    campaign_of = tables.campaign_of
    spent = {
        campaign_of.get(adset_id, "")
        for adset_id, sums in tables.sums.items()
        if sums.get("spend", 0) > 0
    }
    idle: set[str] = set()
    for adset_id in adset_ids:
        campaign = campaign_of.get(adset_id, "")
        if (
            campaign in tables.lately
            and campaign not in tables.built
            and campaign not in spent
            and _running(tables, adset_id)
        ):
            idle.add(campaign)
    return len(idle)


def _running(tables: DayTables, adset_id: str) -> bool:
    """Switched on only while both its own switch and its campaign's are: a
    group under a stopped campaign shows nothing, whatever its own switch
    says - see ``Delivery.PAUSED_ABOVE``."""
    group = tables.groups.get(adset_id)
    campaign = tables.mirror.get(_campaign(tables, adset_id))
    states = (group.delivery if group else "", campaign.delivery if campaign else "")
    return not any(state in OFF_STATES for state in states)


def _parts(tables: DayTables, adset_ids: Iterable[str]) -> list[Part]:
    return [
        (
            _kind(tables, adset_id),
            tables.sums.get(adset_id, {}),
            tables.ours.get(adset_id, 0),
        )
        for adset_id in adset_ids
    ]


def _before_parts(tables: DayTables, adset_ids: Iterable[str]) -> list[Part]:
    return [
        (
            _kind(tables, adset_id),
            tables.before.get(adset_id, {}),
            tables.ours_before.get(adset_id, 0),
        )
        for adset_id in adset_ids
        if adset_id in tables.before or adset_id in tables.ours_before
    ]


def _did_something(tables: DayTables, adset_id: str) -> bool:
    sums = tables.sums.get(adset_id, {})
    if sums.get("spend", 0) > 0:
        return True
    return bool(
        result_count(
            kind=_kind(tables, adset_id),
            sums=sums,
            ours=tables.ours.get(adset_id, 0),
        )
    )


def _kind(tables: DayTables, adset_id: str) -> str:
    """What the group was bought for, the way every screen reads it, with a
    name for what the screens leave uncounted."""
    group = tables.groups.get(adset_id)
    campaign = tables.mirror.get(_campaign(tables, adset_id))
    if group is not None:
        goal, promoted = group.goal, group.promoted
    elif campaign is not None:
        goal, promoted = campaign.goal, campaign.promoted
    else:
        goal, promoted = "", None
    return report_kind(screen_kind(goal, promoted), goal=goal, promoted=promoted)


def _campaign(tables: DayTables, adset_id: str) -> str:
    return tables.campaign_of.get(adset_id, "")


def _money(tables: DayTables, adset_ids: Iterable[str]) -> int:
    return sum(tables.sums.get(adset_id, {}).get("spend", 0) for adset_id in adset_ids)


def _text(amount: int, currency: str) -> str:
    return report_money(amount, currency) if amount > 0 else ""


__all__ = ["pair_report"]
