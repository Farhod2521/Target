"""What this product launched for one account, and what came of it.

Only what this product launched: a campaign built in Ads Manager is the
customer's own business. The figures are the cabinet's own, read through the
selectors the customer's screen reads, so a number quoted down the telephone
is the number they are looking at.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from adskit import MinorUnits
from metaads.writing import is_dry_run_id
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.common.presets import goal_labels
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import NOT_RUNNING, LaunchStep
from app.modules.ads.models import CampaignLaunch
from app.modules.integrations.selectors import active_ad_account
from app.modules.leads.models import Lead
from app.modules.leads.selectors import counts_by_campaign
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.selectors import facts_by_campaign
from app.modules.metrics.selectors.campaigns import DELIVERY_LABELS, campaign_meta
from app.modules.metrics.selectors.facts import people_counts
from app.modules.metrics.selectors.panel import FigureSums
from app.modules.metrics.selectors.results import (
    UNCOUNTED_LABEL,
    screen_kind,
    words_for,
)
from core.metrics import cost_per

PERIODS: tuple[tuple[str, str], ...] = (
    ("today", "Bugun"),
    ("7", "7 kun"),
    ("month", "Shu oy"),
    ("30", "30 kun"),
    ("all", "Hammasi"),
    ("range", "Oraliq"),
)
DEFAULT_PERIOD = "month"
ALL_TIME_DAYS = 3650
UNKNOWN_GOAL = "Noma'lum"


@dataclass(frozen=True, slots=True)
class AdRow:
    """One campaign this product launched: when, for what, what it spent, and
    what that bought. A result this screen cannot count carries ``note``."""

    launch_id: UUID
    campaign_external_id: str
    started_at: datetime | None
    goal: str
    page: str
    delivery_label: str
    is_running: bool
    spend_minor: int
    currency: str
    results: int
    result_word: str
    result_cost_minor: int | None
    result_cost_label: str
    note: str
    campaign_name: str = ""
    impressions: int = 0
    reach: int | None = None
    clicks: int = 0
    link_clicks: int = 0
    leads: int = 0
    ctr_percent: str = ""
    cpm_minor: int | None = None
    cpc_minor: int | None = None


@dataclass(frozen=True, slots=True)
class CurrencySummary:
    """Everything one currency's adverts did; two currencies never add."""

    currency: str
    spend_minor: int
    impressions: int
    clicks: int
    link_clicks: int
    leads: int
    ctr_percent: str
    cpm_minor: int | None
    cpc_minor: int | None
    lead_cost_minor: int | None


@dataclass(frozen=True, slots=True)
class AdWindow:
    """First and last day, both counted; ``refused`` says why a typed stretch
    was replaced by the opening window."""

    period: str
    since: date
    until: date
    refused: str = ""


@dataclass(frozen=True, slots=True)
class Advertising:
    rows: tuple[AdRow, ...]
    window: AdWindow
    running: int
    totals: tuple[tuple[str, int], ...]
    summary: tuple[CurrencySummary, ...]
    hidden: int


def asked_period(value: str) -> str:
    return value if value in dict(PERIODS) else DEFAULT_PERIOD


def asked_window(
    *, period: str, since: date | None, until: date | None, now: datetime
) -> AdWindow:
    """The window asked for; a typed stretch is read as the dashboard reads it."""
    from app.modules.backoffice.selectors.dashboard import asked_window as typed

    asked = asked_period(period)
    if asked == "range":
        found = typed(period=asked, since=since, until=until, today=now.date())
        if found.refused:
            first, last = window(period=DEFAULT_PERIOD, now=now)
            return AdWindow(DEFAULT_PERIOD, first, last, found.refused)
        return AdWindow(asked, found.start, found.end)
    first, last = window(period=asked, now=now)
    return AdWindow(asked, first, last)


def window(*, period: str, now: datetime) -> tuple[date, date]:
    """The pair of days a period means, inclusive at both ends."""
    today = now.date()
    if period == "all":
        return today - timedelta(days=ALL_TIME_DAYS), today
    if period == "30":
        return today - timedelta(days=29), today
    if period == "7":
        return today - timedelta(days=6), today
    if period == "today":
        return today, today
    return today.replace(day=1), today


def _when(launch: CampaignLaunch) -> datetime | None:
    return launch.delivery_started_at or launch.finished_at


def launch_pairs(launches: list[CampaignLaunch]) -> list[tuple[CampaignLaunch, str]]:
    """One row per campaign, the newest launch speaking for it; a launch that
    made no campaign, or only a rehearsal, has none."""
    found = [
        (launch, campaign)
        for launch in launches
        for campaign in ref_field.ref_ids(
            launch.created_refs or {}, LaunchStep.CAMPAIGN
        )
        if campaign and not is_dry_run_id(campaign)
    ]
    found.sort(key=lambda pair: _when(pair[0]) or pair[0].created_at, reverse=True)
    seen: set[str] = set()
    kept = []
    for launch, campaign in found:
        if campaign not in seen:
            seen.add(campaign)
            kept.append((launch, campaign))
    return kept


def result_kind(meta: Any) -> Any:
    """The mirror's kind, or a lead where the mirror has no goal to go on."""
    return meta.kind if meta is not None and meta.goal.strip() else screen_kind("")


def _row(
    *,
    launch: CampaignLaunch,
    campaign: str,
    meta: Any,
    sums: Any,
    leads: int,
    labels: dict[str, str],
    reach: int | None = None,
) -> AdRow:
    kind = result_kind(meta)
    text = words_for(kind)
    spend = sums.spend_minor if sums is not None else 0
    count = (
        leads
        if kind == "lead"
        else int(getattr(sums, text.field, 0) or 0)
        if sums is not None and text.field
        else 0
    )
    delivery = meta.delivery if meta is not None else "unknown"
    goal = str((launch.answers or {}).get("goal") or "")
    note = ""
    if not text.field:
        note = str(meta.note) if meta is not None and meta.note else UNCOUNTED_LABEL
    figures = FigureSums(
        spend_minor=spend,
        impressions=sums.impressions if sums is not None else 0,
        clicks=sums.clicks if sums is not None else 0,
    )
    return AdRow(
        launch_id=launch.id,
        campaign_external_id=campaign,
        started_at=_when(launch),
        goal=labels.get(goal, "") or UNKNOWN_GOAL,
        page=launch.page.name if launch.page is not None else "",
        delivery_label=str(
            meta.delivery_label if meta is not None else DELIVERY_LABELS["unknown"]
        ),
        is_running=meta is not None and str(delivery) not in NOT_RUNNING,
        spend_minor=spend,
        currency=launch.currency,
        results=count,
        result_word=str(text.one) if text.field else "",
        result_cost_minor=cost_per(MinorUnits(spend * text.per), count),
        result_cost_label=str(text.cost_label),
        note=note,
        campaign_name=str(meta.name) if meta is not None else launch.campaign_name,
        impressions=figures.impressions,
        reach=reach,
        clicks=figures.clicks,
        link_clicks=sums.link_clicks if sums is not None else 0,
        leads=leads,
        ctr_percent=figures.ctr_percent,
        cpm_minor=figures.cpm_minor,
        cpc_minor=figures.cpc_minor,
    )


def _within(rows: tuple[AdRow, ...], *, period: str) -> tuple[AdRow, ...]:
    """A window that does not narrow is a broken control: an advert stays when
    it spent, produced something, or is still delivering."""
    if period == "all":
        return rows
    return tuple(r for r in rows if r.spend_minor or r.results or r.is_running)


def _totals(rows: tuple[AdRow, ...]) -> tuple[tuple[str, int], ...]:
    found: dict[str, int] = {}
    for row in rows:
        if row.currency:
            found[row.currency] = found.get(row.currency, 0) + row.spend_minor
    return tuple(sorted(found.items(), key=lambda pair: -pair[1]))


def _summary(rows: tuple[AdRow, ...]) -> tuple[CurrencySummary, ...]:
    found: dict[str, list[AdRow]] = {}
    for row in rows:
        if row.currency:
            found.setdefault(row.currency, []).append(row)
    return tuple(
        sorted(
            (_one_currency(currency, group) for currency, group in found.items()),
            key=lambda row: -row.spend_minor,
        )
    )


def _one_currency(currency: str, rows: list[AdRow]) -> CurrencySummary:
    figures = FigureSums(
        spend_minor=sum(row.spend_minor for row in rows),
        impressions=sum(row.impressions for row in rows),
        clicks=sum(row.clicks for row in rows),
    )
    leads = sum(row.leads for row in rows)
    return CurrencySummary(
        currency=currency,
        spend_minor=figures.spend_minor,
        impressions=figures.impressions,
        clicks=figures.clicks,
        link_clicks=sum(row.link_clicks for row in rows),
        leads=leads,
        ctr_percent=figures.ctr_percent,
        cpm_minor=figures.cpm_minor,
        cpc_minor=figures.cpc_minor,
        lead_cost_minor=cost_per(MinorUnits(figures.spend_minor), leads),
    )


def day_zone(db: Session, *, owner: User) -> Any:
    """The clock a day is cut on, which is the ad account's."""
    account = active_ad_account(db, owner=owner)
    return account.tzinfo() if account is not None else ZoneInfo("UTC")


def read_rows(
    db: Session,
    *,
    owner: User,
    pairs: list[tuple[CampaignLaunch, str]],
    since: date,
    until: date,
    zone: Any,
) -> tuple[AdRow, ...]:
    """One row per launch and campaign, with its figures over these days."""
    ids = frozenset(campaign for _launch, campaign in pairs)
    meta = campaign_meta(db, owner=owner, campaign_ids=ids)
    facts = facts_by_campaign(
        db,
        owner=owner,
        since=since,
        until=until,
        account=EVERY_ACCOUNT,
        scope=lambda model: model.campaign_external_id.in_(ids),
    )
    leads = counts_by_campaign(
        db,
        owner=owner,
        since=datetime.combine(since, time.min, tzinfo=zone),
        until=datetime.combine(until, time.max, tzinfo=zone),
        scope=Lead.campaign_external_id.in_(ids),
    )
    people = people_counts(
        db,
        owner=owner,
        level=MetricLevel.CAMPAIGN,
        since=since,
        until=until,
        ids=ids,
    )
    labels = goal_labels()
    return tuple(
        _row(
            launch=launch,
            campaign=campaign,
            meta=meta.get(campaign),
            sums=facts.get(campaign),
            leads=leads.get(campaign, (0, 0))[0],
            labels=labels,
            reach=people[campaign].reach if campaign in people else None,
        )
        for launch, campaign in pairs
    )


def advertising(db: Session, *, owner: User, window: AdWindow) -> Advertising:
    """Every advert this product launched for one account, newest first."""
    launches = list(
        db.scalars(
            select(CampaignLaunch)
            .options(joinedload(CampaignLaunch.page))
            .where(CampaignLaunch.owner_id == owner.id)
        )
    )
    every = read_rows(
        db,
        owner=owner,
        pairs=launch_pairs(launches),
        since=window.since,
        until=window.until,
        zone=day_zone(db, owner=owner),
    )
    rows = _within(every, period=window.period)
    return Advertising(
        rows=rows,
        window=window,
        running=sum(1 for row in every if row.is_running),
        totals=_totals(rows),
        summary=_summary(rows),
        hidden=len(every) - len(rows),
    )
