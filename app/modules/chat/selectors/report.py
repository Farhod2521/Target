"""One completed week, assembled from the tables the screens already read."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.common import timezone
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.chat.selectors.changes import week_bounds, week_changes
from app.modules.chat.selectors.daily import night_has_passed
from app.modules.chat.selectors.week import (
    campaign_lines,
    campaign_mirror,
    cost_moves,
    figures,
    open_proposals,
    spend_free_ids,
    spend_of,
    sums_by_campaign,
    tallies,
    targets_of,
    week_campaigns,
    week_kind,
)
from app.modules.metrics.constants import EVERY_ACCOUNT
from app.modules.metrics.selectors.facts import campaigns_scope
from app.modules.metrics.selectors.scope import PageCampaigns
from core.chat.daily import ATTENTION_ROWS, census, worth_naming
from core.chat.headline import headline_for
from core.chat.report import WeeklyReport
from core.metrics import Movement, total

DAYS: int = 7


def weekly_report(
    db: Session, *, owner: User, now: datetime, pair: str = ""
) -> WeeklyReport | None:
    """One pair's last completed week, or nothing where there is none."""
    return _report(db, owner=owner, page=_page(db, owner=owner, pair=pair), now=now)


def weekly_reports(db: Session, *, owner: User, now: datetime) -> list[WeeklyReport]:
    """Every page's last completed week, biggest spender first."""
    from app.modules.metrics.selectors.scope import pages_campaigns

    reports = [
        found
        for page in pages_campaigns(db, owner=owner)
        if page.pair_account is not None
        and (found := _report(db, owner=owner, page=page, now=now)) is not None
    ]
    return sorted(reports, key=lambda report: -report.now.spend_minor)


def _page(db: Session, *, owner: User, pair: str) -> PageCampaigns | None:
    from app.modules.metrics.selectors.scope import page_campaigns, pages_campaigns

    if not pair:
        return page_campaigns(db, owner=owner)
    return next(
        (page for page in pages_campaigns(db, owner=owner) if page.key == pair), None
    )


def _report(
    db: Session, *, owner: User, page: PageCampaigns | None, now: datetime
) -> WeeklyReport | None:
    """One page's week, once the page itself has been settled."""
    from app.modules.metrics.selectors.facts import daily_facts

    if page is None:
        return None
    account = page.home
    if page.page is None or account is None:
        return None
    ids = page.ids - spend_free_ids(db, owner=owner, page=page)
    scope = campaigns_scope(ids)

    tzinfo = account.tzinfo()
    currency = account.currency
    today = timezone.localtime(now, tzinfo).date()
    since, until = week_bounds(today=today)

    span = daily_facts(
        db,
        owner=owner,
        since=since - timedelta(days=DAYS),
        until=until,
        tzinfo=tzinfo,
        account=EVERY_ACCOUNT,
        scope=scope,
    )
    days_now, days_before = span[-DAYS:], span[-DAYS * 2 : -DAYS]
    now_totals, before_totals = total(days_now), total(days_before)

    mirror = campaign_mirror(db, owner=owner)
    names = {key: pair[0] for key, pair in mirror.items()}
    kinds = {key: pair[1] for key, pair in mirror.items()}

    sums_now = sums_by_campaign(db, owner=owner, since=since, until=until, scope=scope)
    sums_before = sums_by_campaign(
        db,
        owner=owner,
        since=since - timedelta(days=DAYS),
        until=until - timedelta(days=DAYS),
        scope=scope,
    )
    spend_now, spend_before = spend_of(sums_now), spend_of(sums_before)
    kind = week_kind(sums=sums_now, kinds=kinds)

    leads_now = _leads_in(
        db,
        owner=owner,
        ids=ids,
        since=_start_of(since, tzinfo),
        until=_end_of(until, tzinfo),
    )
    leads_before = _leads_in(
        db,
        owner=owner,
        ids=ids,
        since=_start_of(since - timedelta(days=DAYS), tzinfo),
        until=_end_of(until - timedelta(days=DAYS), tzinfo),
    )
    tally_now = tallies(sums=sums_now, kinds=kinds, leads=leads_now)
    tally_before = tallies(sums=sums_before, kinds=kinds, leads=leads_before)

    moves = cost_moves(now=tally_now, before=tally_before, kind=kind)
    week_now = figures(
        days_now, totals=now_totals, currency=currency, kind=kind, tally=tally_now
    )
    week_before = figures(
        days_before,
        totals=before_totals,
        currency=currency,
        kind=kind,
        tally=tally_before,
    )
    best, barren = campaign_lines(
        leads=leads_now,
        sums=sums_now,
        names=names,
        kinds=kinds,
        kind=kind,
        currency=currency,
    )
    headline = headline_for(moves=moves, now=week_now, before=week_before)
    targets = targets_of(db, owner=owner, ids=ids, names=names)
    lines = week_campaigns(
        db,
        owner=owner,
        sums_now=sums_now,
        sums_before=sums_before,
        leads_now=leads_now,
        leads_before=leads_before,
        names=names,
        kinds=kinds,
        currency=currency,
        until=until,
    )
    return WeeklyReport(
        since=since.strftime("%d.%m"),
        until=until.strftime("%d.%m"),
        now=week_now,
        before=week_before,
        currency=currency,
        page=page.name,
        page_id=page.page.external_id,
        pair=page.key,
        headline=headline,
        elsewhere=_elsewhere(
            db, owner=owner, page=page, since=since, until=until, currency=currency
        ),
        other_currency=_other_currency(
            db, owner=owner, page=page, since=since, until=until
        ),
        move=moves.get(headline, Movement()),
        best=best,
        barren=barren,
        campaigns=lines,
        census=census(lines),
        attention=worth_naming(lines, limit=ATTENTION_ROWS),
        open_proposals=open_proposals(db, owner=owner, targets=targets, now=now),
        final=today > until + timedelta(days=1)
        or night_has_passed(db, owner=owner, account=account, now=now),
        changes=week_changes(
            db,
            owner=owner,
            targets=targets,
            since=_start_of(since, tzinfo),
            until=_end_of(until, tzinfo),
            names=names,
            now_spend=spend_now,
            before_spend=spend_before,
            now=now_totals,
            before=before_totals,
        ),
    )


def _elsewhere(
    db: Session,
    *,
    owner: User,
    page: PageCampaigns,
    since: date,
    until: date,
    currency: str,
) -> str:
    """What Ads Manager's own campaigns spent on this page, as money text."""
    from app.modules.metrics.selectors.campaigns import elsewhere_spend

    if page.page is None:
        return ""
    spent = elsewhere_spend(
        db,
        owner=owner,
        page=page.page,
        since=since,
        until=until,
        currency=currency,
        account=page.pair_account,
    )
    return format_minor(amount_minor=spent, currency=currency) if spent > 0 else ""


def _other_currency(
    db: Session, *, owner: User, page: PageCampaigns, since: date, until: date
) -> tuple[str, ...]:
    from app.modules.metrics.selectors.lead_sources import other_currency_spend

    return tuple(
        format_minor(amount_minor=amount, currency=code)
        for code, amount in other_currency_spend(
            db, owner=owner, ids=page.foreign, since=since, until=until
        )
    )


def _leads_in(
    db: Session, *, owner: User, ids: frozenset[str], since: datetime, until: datetime
) -> dict[str, tuple[int, int]]:
    from app.modules.leads.selectors import counts_by_campaign

    counted = counts_by_campaign(db, owner=owner, since=since, until=until)
    return {key: value for key, value in counted.items() if key in ids}


def _start_of(day: date, tzinfo: ZoneInfo) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min), tzinfo)


def _end_of(day: date, tzinfo: ZoneInfo) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.max), tzinfo)


__all__ = ["weekly_report", "weekly_reports"]
