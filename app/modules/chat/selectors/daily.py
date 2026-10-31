"""Every chosen pair's day, assembled for the morning message.

Read-only, and every figure is one the screens already show: the day's rows
are the ones the dashboard reads, the lead count is the customers screen's,
and a result is counted in the column the numbers screen counts it in.

**A pair, not a page or an ad account.** A page paid from two ad accounts is
two cabinets, so its day is two entries. Every pair the subscription holds has
an entry, the ones that spent nothing included.

**One clock for all of them**: the cabinet's own account, the calendar every
screen the owner compares it against is drawn on. Nothing here judges the day
and nothing calls a model: the message is the figures.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import timezone
from app.modules.accounts.models import User
from app.modules.chat.constants import DAILY_REREAD_AFTER_HOURS
from app.modules.chat.selectors.day_figures import DayTables, day_tables
from app.modules.chat.selectors.day_groups import ads_by_group, pair_report
from app.modules.chat.selectors.day_tables import (
    PageMoney,
    apart_spend,
    day_pairs,
    money_by_pair,
)
from app.modules.chat.selectors.scope import in_subscription, subscribed_accounts
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from core.chat.day_report import DailyReport


def daily_reports(
    db: Session, *, owner: User, now: datetime, day: date | None = None
) -> list[DailyReport]:
    """One report per chosen pair, the biggest spender first.

    ``day`` is the morning's day unless a press or a command asks for another
    - an older one, or today so far. Empty with no ad account to keep a
    calendar by. A pair that spent nothing has a quiet report, listed last.
    """
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return []

    latest = report_day(account=clock, now=now)
    day = day or latest
    tzinfo, currency = clock.tzinfo(), clock.currency
    start, end = _start(day, tzinfo), _end(day, tzinfo)
    tables = day_tables(db, owner=owner, day=day, start=start, end=end)
    # The report goes out when the night's re-read has not happened - a sync
    # that failed must not cost somebody the day - and says so.
    ongoing = day > latest
    final = day < latest or (
        not ongoing and night_has_passed(db, owner=owner, account=clock, now=now)
    )
    pairs = day_pairs(db, owner=owner, pages=tables.pages)
    money = money_by_pair(db, owner=owner, fallback=currency)
    placed = _by_pair(pairs.of, tables.campaign_of)
    unplaced = _by_pair(pairs.unplaced, tables.campaign_of)
    ads = ads_by_group(tables.ads)

    reports = []
    for pair in pairs.names:
        paid = money.get(pair, PageMoney(currency=currency))
        reports.append(
            pair_report(
                tables=tables,
                ads=ads,
                day=day,
                final=final,
                ongoing=ongoing,
                currency=paid.currency,
                pair=pair,
                pairs=pairs,
                adset_ids=_in_currency(tables, placed.get(pair, []), paid),
                unplaced_minor=sum(
                    tables.sums.get(adset_id, {}).get("spend", 0)
                    for adset_id in unplaced.get(pair, ())
                ),
                other_currency=apart_spend(db, owner=owner, money=paid, day=day),
            )
        )
    return sorted(reports, key=lambda report: (-report.spend_minor, report.title))


def _in_currency(
    tables: DayTables, adset_ids: list[str], money: PageMoney
) -> list[str]:
    """The pair's groups, less the ones paid in another currency: their money
    is on the report's own line instead."""
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
    return current_day(account=account, now=now) - timedelta(days=1)


def current_day(*, account: AdAccount, now: datetime) -> date:
    """Today on the account's clock - the day still running."""
    return timezone.localtime(now, account.tzinfo()).date()


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


def _by_pair(of: Mapping[str, str], groups: Iterable[str]) -> dict[str, list[str]]:
    """``{pair key: these ad groups}``. A group the boundary leaves out is not
    reported at all - its figures, its campaign and its name."""
    found: dict[str, list[str]] = defaultdict(list)
    for adset_id in groups:
        pair = of.get(adset_id)
        if pair is not None:
            found[pair].append(adset_id)
    return dict(found)


def _start(day: date, tzinfo: ZoneInfo) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min), tzinfo)


def _end(day: date, tzinfo: ZoneInfo) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.max), tzinfo)


__all__ = [
    "cabinet_clock",
    "current_day",
    "daily_reports",
    "night_has_passed",
    "report_day",
]
