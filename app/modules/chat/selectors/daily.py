"""One pair's finished day, assembled for the daily message."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import timezone
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.chat.constants import DAILY_REREAD_AFTER_HOURS, DAILY_USUAL_DAYS
from app.modules.chat.selectors.day_tables import (
    DayPairs,
    DayTables,
    Mirror,
    PageMoney,
    apart_spend,
    campaign_causes,
    campaign_line,
    campaign_sums,
    day_pairs,
    day_tables,
    money_by_pair,
)
from app.modules.chat.selectors.scope import in_subscription, subscribed_accounts
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from core.chat.daily import ATTENTION_ROWS, DailyReport, census, worth_naming
from core.chat.day_review import MAX_DAY_CAMPAIGNS


def daily_reports(db: Session, *, owner: User, now: datetime) -> list[DailyReport]:
    """One report per pair that spent, biggest spender first."""
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return []
    day = report_day(account=clock, now=now)
    tzinfo, currency = clock.tzinfo(), clock.currency
    since, before = day - timedelta(days=DAILY_USUAL_DAYS), day - timedelta(days=1)
    tables = day_tables(
        db,
        owner=owner,
        day=day,
        since=since,
        before=before,
        starts=(_start(day, tzinfo), _start(since, tzinfo)),
        ends=(_end(day, tzinfo), _end(before, tzinfo)),
    )
    final = night_has_passed(db, owner=owner, account=clock, now=now)
    pairs = day_pairs(db, owner=owner, pages=tables.pages)
    open_proposals = _proposals_by_pair(db, owner=owner, pairs=pairs, now=now)
    money = money_by_pair(db, owner=owner, fallback=currency)
    causes = {
        code: campaign_causes(db, owner=owner, currency=code, day=day)
        for code in {row.currency for row in money.values()} | {currency}
    }
    elsewhere = _by_pair(pairs, tables.elsewhere)
    reports = []
    for pair, adset_ids in _by_pair(pairs, tables.campaign_of).items():
        paid = money.get(pair, PageMoney(currency=currency))
        reports.append(
            _report(
                tables=tables,
                day=day,
                day_end=_end(day, tzinfo),
                final=final,
                currency=paid.currency,
                pair=pair,
                pairs=pairs,
                adset_ids=_in_currency(tables, adset_ids, paid),
                causes=causes[paid.currency],
                open_proposals=open_proposals.get(pair, 0),
                elsewhere_minor=sum(
                    tables.elsewhere[adset_id] for adset_id in elsewhere.get(pair, ())
                ),
                other_currency=apart_spend(db, owner=owner, money=paid, day=day),
            )
        )
    return sorted(reports, key=lambda report: -report.spend_minor)


def _in_currency(
    tables: DayTables, adset_ids: list[str], money: PageMoney
) -> list[str]:
    if not money.apart:
        return adset_ids
    return [
        adset_id
        for adset_id in adset_ids
        if tables.campaign_of.get(adset_id, "") not in money.apart
    ]


def cabinet_clock(db: Session, *, owner: User) -> AdAccount | None:
    """The ad account whose calendar the reports are kept on."""
    accounts = subscribed_accounts(db, owner=owner)
    return accounts[0] if accounts else None


def report_day(*, account: AdAccount, now: datetime) -> date:
    """The day a report sent now is about: the last to end on the account's clock."""
    return timezone.localtime(now, account.tzinfo()).date() - timedelta(days=1)


def night_has_passed(
    db: Session, *, owner: User, account: AdAccount, now: datetime
) -> bool:
    """Whether the night's work over the finished day is done."""
    from app.modules.agent.selectors import finished_since, is_enabled

    day = report_day(account=account, now=now)
    ended = _start(day + timedelta(days=1), account.tzinfo())
    where = (
        MetricsDaily.owner_id == owner.id,
        in_subscription(MetricsDaily.ad_account_id),
        MetricsDaily.level == MetricLevel.ADSET,
        MetricsDaily.date == day,
    )
    spent = set(db.scalars(select(MetricsDaily.ad_account_id).where(*where).distinct()))
    if not spent:
        return False
    reread = set(
        db.scalars(
            select(MetricsDaily.ad_account_id)
            .where(
                *where,
                MetricsDaily.synced_at
                >= ended + timedelta(hours=DAILY_REREAD_AFTER_HOURS),
            )
            .distinct()
        )
    )
    if spent - reread:
        return False
    return not is_enabled(db, owner=owner) or finished_since(
        db, owner=owner, since=ended
    )


def _by_pair(pairs: DayPairs, groups: Iterable[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for adset_id in groups:
        pair = pairs.of.get(adset_id)
        if pair is not None:
            found[pair].append(adset_id)
    return dict(found)


def _report(
    *,
    tables: DayTables,
    day: date,
    day_end: datetime,
    final: bool,
    currency: str,
    pair: str,
    pairs: DayPairs,
    adset_ids: list[str],
    causes: dict[str, Any],
    open_proposals: int,
    elsewhere_minor: int,
    other_currency: tuple[str, ...],
) -> DailyReport:
    """One pair's day: what spent, what was switched on and spent nothing."""
    figures = campaign_sums(tables=tables, adset_ids=adset_ids)
    spent = sorted(
        (key for key, row in figures.items() if row["day"]["spend"] > 0),
        key=lambda key: -figures[key]["day"]["spend"],
    )
    total = sum(figures[key]["day"]["spend"] for key in spent)
    lines = tuple(
        campaign_line(
            figures=figures[key],
            info=tables.mirror.get(key) or Mirror(key, key, "", "", learning=False),
            currency=currency,
            cause=causes.get(key),
        )
        for key in spent
    )
    attention = worth_naming(lines, limit=ATTENTION_ROWS)
    named = set(attention)
    listed = tuple(
        row
        for index, row in enumerate(lines)
        if index < MAX_DAY_CAMPAIGNS or row in named
    )
    rest_minor = total - sum(row.spend_minor for row in listed)
    return DailyReport(
        day=day,
        day_text=day.strftime("%d.%m"),
        currency=currency,
        spend=format_minor(amount_minor=total, currency=currency),
        spend_minor=total,
        other_currency=other_currency,
        final=final,
        page=pairs.names.get(pair, ""),
        page_id=pairs.pages.get(pair, ""),
        pair=pair,
        campaigns=listed,
        day_census=census(lines),
        attention=attention,
        spenders=len(spent),
        rest=format_minor(amount_minor=rest_minor, currency=currency)
        if rest_minor > 0
        else "",
        rest_minor=rest_minor,
        idle=sum(
            1
            for key in figures
            if key not in spent
            and (info := tables.mirror.get(key))
            and info.delivery == Delivery.ACTIVE
            and not (info.created_time and info.created_time > day_end)
        ),
        open_proposals=open_proposals,
        elsewhere=(
            format_minor(amount_minor=elsewhere_minor, currency=currency)
            if elsewhere_minor > 0
            else ""
        ),
    )


def _proposals_by_pair(
    db: Session, *, owner: User, pairs: DayPairs, now: datetime
) -> dict[str, int]:
    from app.modules.agent.selectors import waiting

    found: dict[str, int] = defaultdict(int)
    for row in waiting(db, owner=owner, now=now):
        pair = pairs.of.get(row.target_parent_id or row.target_external_id)
        if pair is not None:
            found[pair] += 1
    return dict(found)


def _start(day: date, tzinfo: ZoneInfo) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min), tzinfo)


def _end(day: date, tzinfo: ZoneInfo) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.max), tzinfo)


__all__ = ["cabinet_clock", "daily_reports", "night_has_passed", "report_day"]
