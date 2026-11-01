"""Every chosen pair's day, assembled for the morning message.

Read-only, and every figure is one the screens already show: the day's rows
are the ones the dashboard reads, the lead count is the customers screen's,
and a result is counted in the column the numbers screen counts it in.

**A pair, not a page or an ad account.** A page paid from two ad accounts is
two cabinets, so its day is two entries. Every pair the subscription holds has
an entry, the ones that spent nothing included.

**All of a pair's money.** Campaigns built in Ads Manager count beside the ones
built here, so the total is what left the account. Money on a page the owner
has not chosen is named once and added to nothing.

**One calendar for all of them**: the cabinet's own account, the one every
screen the owner compares it against is drawn on. Nothing here judges the day
and nothing calls a model: the message is the figures.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import timezone
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.chat.constants import DAILY_REREAD_AFTER_HOURS
from app.modules.chat.selectors.changes import week_bounds
from app.modules.chat.selectors.day_figures import (
    DayTables,
    day_tables,
    outside_spend,
)
from app.modules.chat.selectors.day_groups import pair_report
from app.modules.chat.selectors.day_tables import (
    PageMoney,
    apart_spend,
    day_pairs,
    money_by_pair,
)
from app.modules.chat.selectors.scope import (
    in_subscription,
    reads_ads_manager,
    subscribed_accounts,
)
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import INSIGHT_LEVELS, MetricLevel
from app.modules.metrics.models import MetricsDaily
from core.chat.day_report import DailyReport, DayBook, DayTotal

WEEK_DAYS: Final = 7


def daily_book(
    db: Session, *, owner: User, now: datetime, day: date | None = None
) -> DayBook | None:
    """One owner's day, the biggest spender first.

    ``day`` is the morning's day unless a press or a command asks for another
    - an older one, or today so far. Nothing with no ad account to keep a
    calendar by. A pair that spent nothing has a quiet report, listed last.
    """
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return None

    latest = report_day(account=clock, now=now)
    day = day or latest
    # The report goes out when the night's re-read has not happened - a sync
    # that failed must not cost somebody the day - and says so.
    ongoing = day > latest
    return _book(
        db,
        owner=owner,
        now=now,
        clock=clock,
        since=day,
        until=day,
        day_text=day.strftime("%d.%m"),
        final=day < latest
        or (not ongoing and night_has_passed(db, owner=owner, account=clock, now=now)),
        ongoing=ongoing,
    )


def weekly_book(
    db: Session, *, owner: User, now: datetime, since: date | None = None
) -> DayBook | None:
    """One owner's completed week, Monday to Sunday. ``since`` is its Monday,
    the last finished week's unless a press names an older one."""
    clock = cabinet_clock(db, owner=owner)
    if clock is None:
        return None
    today = current_day(account=clock, now=now)
    since = since or week_bounds(today=today)[0]
    until = since + timedelta(days=WEEK_DAYS - 1)
    return _book(
        db,
        owner=owner,
        now=now,
        clock=clock,
        since=since,
        until=until,
        day_text=f"{since:%d.%m} – {until:%d.%m}",
        final=week_is_final(db, owner=owner, account=clock, now=now, until=until),
        weekly=True,
    )


def week_is_final(
    db: Session, *, owner: User, account: AdAccount, now: datetime, until: date
) -> bool:
    """A week's last day is settled by its own night, or by the day after it."""
    return current_day(account=account, now=now) > until + timedelta(
        days=1
    ) or night_has_passed(db, owner=owner, account=account, now=now)


def _book(
    db: Session,
    *,
    owner: User,
    now: datetime,
    clock: AdAccount,
    since: date,
    until: date,
    day_text: str,
    final: bool,
    ongoing: bool = False,
    weekly: bool = False,
) -> DayBook:
    tzinfo, currency = clock.tzinfo(), clock.currency
    span = until - since + timedelta(days=1)
    tables = day_tables(
        db,
        owner=owner,
        since=since,
        until=until,
        lead_window=(_start(since, tzinfo), _end(until, tzinfo)),
        before_window=(_start(since - span, tzinfo), _end(until - span, tzinfo)),
    )
    pairs = day_pairs(db, owner=owner, pages=tables.pages)
    money = money_by_pair(db, owner=owner, fallback=currency)
    placed = _by_pair(pairs.of, tables.campaign_of)
    describes_elsewhere = reads_ads_manager(db, owner=owner)

    reports = []
    for pair in pairs.names:
        paid = money.get(pair, PageMoney(currency=currency))
        adset_ids = _in_currency(tables, placed.get(pair, []), paid)
        reports.append(
            pair_report(
                tables=tables,
                day=since,
                day_text=day_text,
                ongoing=ongoing,
                currency=paid.currency,
                pair=pair,
                pairs=pairs,
                adset_ids=adset_ids,
                other_currency=apart_spend(
                    db, owner=owner, money=paid, since=since, until=until
                ),
                describes_elsewhere=describes_elsewhere,
                open_proposals=_waiting(
                    db, owner=owner, tables=tables, adsets=adset_ids, now=now
                )
                if weekly
                else 0,
            )
        )
    reports.sort(key=lambda report: (-report.spend_minor, report.title))
    return DayBook(
        day=since,
        until=until,
        day_text=day_text,
        weekly=weekly,
        reports=tuple(reports),
        totals=_totals(reports),
        outside=outside_spend(
            db, owner=owner, since=since, until=until, placed=pairs.of
        ),
        final=final,
        ongoing=ongoing,
    )


def _waiting(
    db: Session, *, owner: User, tables: DayTables, adsets: list[str], now: datetime
) -> int:
    """The agent's proposals on this pair's campaigns that wait for an answer."""
    from app.modules.chat.selectors.week import open_proposals, targets_of

    built = frozenset(
        campaign
        for adset_id in adsets
        if (campaign := tables.campaign_of.get(adset_id, "")) in tables.built
    )
    targets = targets_of(db, owner=owner, ids=built, names={})
    return open_proposals(db, owner=owner, targets=targets, now=now)


def _totals(reports: Iterable[DailyReport]) -> tuple[DayTotal, ...]:
    """The day's money, one figure a currency: nothing here converts money."""
    spent: dict[str, int] = defaultdict(int)
    before: dict[str, int] = defaultdict(int)
    for report in reports:
        before[report.currency] += report.before_minor
        if report.spend_minor > 0:
            spent[report.currency] += report.spend_minor
    return tuple(
        DayTotal(
            spend=format_minor(amount_minor=amount, currency=code),
            before=format_minor(amount_minor=before[code], currency=code)
            if before[code] > 0
            else "",
        )
        for code, amount in sorted(spent.items(), key=lambda row: -row[1])
    )


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
    """Whether the night's work over the finished day is done.

    **Every level of every account, each by its own clock.** A read stops at
    the level it fails on, and an account in another timezone finishes the
    same date hours later, so one level's row or one clock would call a day
    done that is still being counted.
    """
    from app.modules.agent.selectors import finished_since, is_enabled

    day = report_day(account=account, now=now)
    newest: dict[object, dict[str, datetime]] = defaultdict(dict)
    for ad_account_id, level, synced_at in db.execute(
        select(
            MetricsDaily.ad_account_id,
            MetricsDaily.level,
            func.max(MetricsDaily.synced_at),
        )
        .where(
            MetricsDaily.owner_id == owner.id,
            in_subscription(MetricsDaily.ad_account_id),
            MetricsDaily.date == day,
        )
        .group_by(MetricsDaily.ad_account_id, MetricsDaily.level)
    ):
        newest[ad_account_id][str(level)] = synced_at
    spent = [key for key, levels in newest.items() if str(MetricLevel.ADSET) in levels]
    if not spent:
        return False
    zones = {
        row.id: row.tzinfo()
        for row in db.scalars(select(AdAccount).where(AdAccount.id.in_(spent)))
    }
    for key in spent:
        ended = _start(day + timedelta(days=1), zones.get(key, account.tzinfo()))
        floor = ended + timedelta(hours=DAILY_REREAD_AFTER_HOURS)
        read = [newest[key].get(str(level)) for level in INSIGHT_LEVELS]
        if any(stamp is None or stamp < floor for stamp in read):
            return False
    return not is_enabled(db, owner=owner) or finished_since(
        db, owner=owner, since=_start(day + timedelta(days=1), account.tzinfo())
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
    "daily_book",
    "night_has_passed",
    "report_day",
    "week_is_final",
    "weekly_book",
]
