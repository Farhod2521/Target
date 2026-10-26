"""Groups spending today with nothing of their own kind to show for it."""

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import AdSet
from app.modules.agent.selectors.diagnoses import kind_usuals, usual_costs
from app.modules.agent.selectors.window import start_of
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent.same_day import MIN_IMPRESSIONS, TodayGroup, burning
from core.metrics import Outcome, heard_leads, outcome_for

RESULT_COLUMNS: Final[dict[str, str]] = {
    "lead": "leads_reported",
    "click": "results_reported",
    "chat": "results_reported",
    "call": "results_reported",
    "recall": "recallers",
    "profile": "profile_visits",
    "site_lead": "leads_reported",
}
TODAY_KINDS: Final = frozenset(RESULT_COLUMNS) - {"site_lead"}
SUMMED: Final = (
    "spend_minor",
    "impressions",
    "leads_reported",
    "inline_link_clicks",
    "results_reported",
    "recallers",
    "profile_visits",
)


@dataclass(frozen=True, slots=True)
class Burning:
    """One group whose money is going today with nothing of its kind back."""

    adset_id: str
    name: str
    campaign_pk: str
    spend_minor: int
    currency: str
    impressions: int
    kind: Outcome
    day: date


def burning_groups(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    now: datetime,
    hidden_adsets: Collection[str] = (),
) -> list[Burning]:
    """Today's groups the same-day bar says are spending for nothing."""
    tzinfo = account.tzinfo()
    today = now.astimezone(tzinfo).date()
    figures = {
        key: row
        for key, row in adset_sums(
            db, owner=owner, account=account, since=today, until=today
        ).items()
        if row["spend_minor"] > 0
        and row["impressions"] >= MIN_IMPRESSIONS
        and key not in hidden_adsets
    }
    if not figures:
        return []
    days = _groups_today(
        db, owner=owner, figures=figures, today=today, now=now, tzinfo=tzinfo
    )
    usual = group_usuals(
        db,
        owner=owner,
        account=account,
        adset_ids=[row.external_id for row, _kind, _day in days],
        hidden=hidden_adsets,
    )
    days = [
        (row, kind, replace(day, usual_cost_minor=usual(row.external_id, kind)))
        for row, kind, day in days
    ]
    return [
        Burning(
            adset_id=row.external_id,
            name=row.name or row.external_id,
            campaign_pk=str(row.campaign_id or ""),
            spend_minor=day.spend_minor,
            currency=account.currency,
            impressions=day.impressions,
            kind=kind,
            day=today,
        )
        for row, kind, day in days
        if burning(day)
    ]


def _groups_today(
    db: Session,
    *,
    owner: User,
    figures: dict[str, dict[str, Any]],
    today: date,
    now: datetime,
    tzinfo: Any,
) -> list[tuple[AdSet, Outcome, TodayGroup]]:
    """The running groups among today's figures, each with its day so far."""
    from app.modules.leads.selectors import counts_by_adset

    mirror = db.scalars(
        select(AdSet)
        .where(
            AdSet.owner_id == owner.id,
            AdSet.external_id.in_(list(figures)),
            AdSet.delivery == Delivery.ACTIVE,
        )
        .order_by(AdSet.name)
    )
    ours = counts_by_adset(db, owner=owner, since=start_of(today, tzinfo), until=now)
    return [
        (
            row,
            kind,
            _today(row=row, kind=kind, sums=figures[row.external_id], ours=ours),
        )
        for row in mirror
        if (kind := kind_of(row.optimization_goal_raw, row.promoted_object_raw))
        in TODAY_KINDS
    ]


def owners_spending_today(db: Session, *, now: datetime) -> set[UUID]:
    """Which accounts have a group shown enough today to be judged at all."""
    m = MetricsDaily
    return set(
        db.scalars(
            select(m.owner_id)
            .where(
                m.level == MetricLevel.ADSET,
                m.date >= now.date() - timedelta(days=1),
                m.date <= now.date() + timedelta(days=1),
                m.spend_minor > 0,
                m.impressions >= MIN_IMPRESSIONS,
            )
            .distinct()
        )
    )


def kind_of(goal: str, promoted: Mapping[str, object] | None = None) -> Outcome:
    """What a group was bought for; an unsynced goal is read as a lead."""
    return outcome_for(goal, promoted) if (goal or "").strip() else "lead"


def _today(
    *,
    row: AdSet,
    kind: Outcome,
    sums: dict[str, int],
    ours: dict[str, tuple[int, int]],
) -> TodayGroup:
    results = sums[RESULT_COLUMNS[kind]]
    if kind == "lead":
        results = heard_leads(
            ours=ours.get(row.external_id, (0, 0))[0], reported=results
        )
    budget = row.daily_budget_minor or (
        row.campaign.daily_budget_minor if row.campaign_id else None
    )
    return TodayGroup(
        adset_id=row.external_id,
        spend_minor=sums["spend_minor"],
        impressions=sums["impressions"],
        results=results,
        daily_budget_minor=budget or None,
    )


def group_usuals(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    adset_ids: Collection[str],
    hidden: Collection[str] = (),
) -> Callable[[str, str], int | None]:
    """What one result usually costs, per group: the one "odatda" there is."""
    own = usual_costs(db, owner=owner, adset_ids=adset_ids, currency=account.currency)
    kinds: dict[str, int] | None = None

    def usual(adset_id: str, kind: str) -> int | None:
        nonlocal kinds
        if adset_id in own:
            return own[adset_id]
        if kinds is None:
            kinds = kind_usuals(db, owner=owner, account=account, hidden=hidden)
        return kinds.get(kind)

    return usual


def adset_sums(
    db: Session, *, owner: User, account: AdAccount, since: date, until: date
) -> dict[str, dict[str, Any]]:
    """Every group's figures over these days, summed, keyed by its id."""
    m = MetricsDaily
    rows = db.execute(
        select(
            m.adset_external_id,
            *(func.sum(getattr(m, column)).label(column) for column in SUMMED),
        )
        .where(
            *cabinet_where(db, owner=owner, account=account),
            m.date >= since,
            m.date <= until,
            m.adset_external_id != "",
        )
        .group_by(m.adset_external_id)
    ).mappings()
    return {
        row["adset_external_id"]: {column: int(row[column] or 0) for column in SUMMED}
        for row in rows
    }


__all__ = [
    "RESULT_COLUMNS",
    "TODAY_KINDS",
    "Burning",
    "adset_sums",
    "burning_groups",
    "group_usuals",
    "kind_of",
    "owners_spending_today",
]
