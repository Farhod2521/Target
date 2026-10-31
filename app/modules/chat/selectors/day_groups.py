"""One pair's day, group by group, with each group's adverts under it.

The rung the message is read at: «Campaign — Group», then the adverts. Split
from :mod:`app.modules.chat.selectors.daily`, which reads the day once for every
pair; this turns one pair's slice of it into a report.

**Running first.** A group is listed under "switched on now" or "ran
yesterday and is off now" by its state at this minute, the group's own or
its campaign's; within each half the biggest spender leads.
"""

from collections import defaultdict
from collections.abc import Mapping
from datetime import date

from app.common.money import format_minor
from app.modules.chat.selectors.day_figures import AdRow, DayTables
from app.modules.chat.selectors.day_lines import figure_of, result_count
from app.modules.chat.selectors.day_tables import DayPairs
from app.modules.metrics.selectors.results import screen_kind
from core.chat.daily import OFF_STATES
from core.chat.day_report import AdLine, DailyReport, GroupLine
from core.metrics import Outcome


def pair_report(
    *,
    tables: DayTables,
    ads: Mapping[str, list[AdRow]],
    day: date,
    final: bool,
    ongoing: bool,
    currency: str,
    pair: str,
    pairs: DayPairs,
    adset_ids: list[str],
    unplaced_minor: int,
    other_currency: tuple[str, ...],
) -> DailyReport:
    """One pair's day: its total, and every group that spent or brought."""
    kinds = {adset_id: _kind(tables, adset_id) for adset_id in adset_ids}
    shown = [
        adset_id
        for adset_id in adset_ids
        if _spent(tables, adset_id)
        or result_count(
            kind=kinds[adset_id],
            sums=tables.sums.get(adset_id, {}),
            ours=tables.ours.get(adset_id, 0),
        )
    ]
    groups = sorted(
        (
            _group(
                tables=tables,
                ads=ads.get(adset_id, []),
                adset_id=adset_id,
                kind=kinds[adset_id],
                currency=currency,
            )
            for adset_id in shown
        ),
        key=lambda group: (not group.running, -group.figure.spend_minor),
    )
    return DailyReport(
        day=day,
        day_text=day.strftime("%d.%m"),
        currency=currency,
        pair=pair,
        page=pairs.names.get(pair, ""),
        page_id=pairs.pages.get(pair, ""),
        account=pairs.accounts.get(pair, ""),
        figure=figure_of(
            parts=[
                (
                    kinds[adset_id],
                    tables.sums.get(adset_id, {}),
                    tables.ours.get(adset_id, 0),
                )
                for adset_id in shown
            ],
            currency=currency,
        ),
        final=final,
        ongoing=ongoing,
        groups=tuple(groups),
        campaigns=len({tables.campaign_of.get(adset_id, "") for adset_id in shown}),
        unplaced=(
            format_minor(amount_minor=unplaced_minor, currency=currency)
            if unplaced_minor > 0
            else ""
        ),
        other_currency=other_currency,
    )


def _group(
    *,
    tables: DayTables,
    ads: list[AdRow],
    adset_id: str,
    kind: Outcome,
    currency: str,
) -> GroupLine:
    """One group's day, and its adverts' under it, the biggest spender first.

    Switched on only while both its own switch and its campaign's are: a
    group under a stopped campaign shows nothing, whatever its own switch
    says - see ``Delivery.PAUSED_ABOVE``.
    """
    campaign = tables.mirror.get(tables.campaign_of.get(adset_id, ""))
    group = tables.groups.get(adset_id)
    states = (
        group.delivery if group else "",
        campaign.delivery if campaign else "",
    )
    return GroupLine(
        campaign=campaign.name if campaign else "",
        name=group.name if group else adset_id,
        running=not any(state in OFF_STATES for state in states),
        figure=figure_of(
            parts=[(kind, tables.sums.get(adset_id, {}), tables.ours.get(adset_id, 0))],
            currency=currency,
        ),
        ads=tuple(
            AdLine(
                name=row.name,
                figure=figure_of(parts=[(kind, row.sums, row.ours)], currency=currency),
            )
            for row in sorted(ads, key=lambda row: -row.sums.get("spend", 0))
        ),
    )


def _kind(tables: DayTables, adset_id: str) -> Outcome:
    """What the group's campaign was bought for, the way every screen reads it."""
    campaign = tables.mirror.get(tables.campaign_of.get(adset_id, ""))
    if campaign is None:
        return screen_kind("")
    return screen_kind(campaign.goal, campaign.promoted)


def _spent(tables: DayTables, adset_id: str) -> bool:
    return tables.sums.get(adset_id, {}).get("spend", 0) > 0


def ads_by_group(ads: Mapping[str, AdRow]) -> dict[str, list[AdRow]]:
    found: dict[str, list[AdRow]] = defaultdict(list)
    for row in ads.values():
        found[row.adset_id].append(row)
    return dict(found)


__all__ = ["ads_by_group", "pair_report"]
