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
from app.modules.metrics.constants import EVERY_ACCOUNT
from app.modules.metrics.selectors import facts_by_campaign
from app.modules.metrics.selectors.campaigns import DELIVERY_LABELS, campaign_meta
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


@dataclass(frozen=True, slots=True)
class Advertising:
    rows: tuple[AdRow, ...]
    period: str
    running: int
    totals: tuple[tuple[str, int], ...]
    hidden: int


def asked_period(value: str) -> str:
    return value if value in dict(PERIODS) else DEFAULT_PERIOD


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


def _pairs(launches: list[CampaignLaunch]) -> list[tuple[CampaignLaunch, str]]:
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


def _row(
    *,
    launch: CampaignLaunch,
    campaign: str,
    meta: Any,
    sums: Any,
    leads: int,
    labels: dict[str, str],
) -> AdRow:
    kind = meta.kind if meta is not None and meta.goal.strip() else screen_kind("")
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


def advertising(
    db: Session, *, owner: User, now: datetime, period: str = DEFAULT_PERIOD
) -> Advertising:
    """Every advert this product launched for one account, newest first."""
    launches = list(
        db.scalars(
            select(CampaignLaunch)
            .options(joinedload(CampaignLaunch.page))
            .where(CampaignLaunch.owner_id == owner.id)
        )
    )
    pairs = _pairs(launches)
    ids = frozenset(campaign for _launch, campaign in pairs)
    since, until = window(period=period, now=now)
    meta = campaign_meta(db, owner=owner, campaign_ids=ids)
    facts = facts_by_campaign(
        db,
        owner=owner,
        since=since,
        until=until,
        account=EVERY_ACCOUNT,
        scope=lambda model: model.campaign_external_id.in_(ids),
    )
    account = active_ad_account(db, owner=owner)
    zone = account.tzinfo() if account is not None else ZoneInfo("UTC")
    leads = counts_by_campaign(
        db,
        owner=owner,
        since=datetime.combine(since, time.min, tzinfo=zone),
        until=datetime.combine(until, time.max, tzinfo=zone),
        scope=Lead.campaign_external_id.in_(ids),
    )
    labels = goal_labels()
    every = tuple(
        _row(
            launch=launch,
            campaign=campaign,
            meta=meta.get(campaign),
            sums=facts.get(campaign),
            leads=leads.get(campaign, (0, 0))[0],
            labels=labels,
        )
        for launch, campaign in pairs
    )
    rows = _within(every, period=period)
    return Advertising(
        rows=rows,
        period=period,
        running=sum(1 for row in every if row.is_running),
        totals=_totals(rows),
        hidden=len(every) - len(rows),
    )
