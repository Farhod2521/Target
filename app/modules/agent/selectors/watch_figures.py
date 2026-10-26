"""The figures the watch reads a group's present on."""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import LEARNING_LIMITED, Delivery
from app.modules.ads.models import Ad, AdSet
from app.modules.agent.selectors.same_day import RESULT_COLUMNS, adset_sums
from app.modules.agent.selectors.window import start_of
from app.modules.integrations.models import AdAccount
from core.agent.launch_watch import WatchedGroup
from core.metrics import Outcome


def since_born(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    born: dict[str, datetime],
    groups: list[AdSet],
    now: datetime,
) -> dict[str, dict[str, int]]:
    """Each group's figures, with our own count of its leads beside Meta's."""
    if not groups:
        return {}
    first = min(born[row.external_id] for row in groups)
    since = first.astimezone(account.tzinfo()).date()
    return _summed(
        db, owner=owner, account=account, groups=groups, since=since, now=now
    )


def today_so_far(
    db: Session, *, owner: User, account: AdAccount, groups: list[AdSet], now: datetime
) -> dict[str, dict[str, int]]:
    """A running group's day so far: the finished days are the watch's own."""
    if not groups:
        return {}
    since = now.astimezone(account.tzinfo()).date()
    return _summed(
        db, owner=owner, account=account, groups=groups, since=since, now=now
    )


def _summed(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    groups: list[AdSet],
    since: date,
    now: datetime,
) -> dict[str, dict[str, int]]:
    from app.modules.leads.selectors import counts_by_adset

    tzinfo = account.tzinfo()
    sums = adset_sums(
        db,
        owner=owner,
        account=account,
        since=since,
        until=now.astimezone(tzinfo).date(),
    )
    ours = counts_by_adset(db, owner=owner, since=start_of(since, tzinfo), until=now)
    return {
        row.external_id: {
            **sums.get(row.external_id, {}),
            "ours_leads": ours.get(row.external_id, (0, 0))[0],
        }
        for row in groups
    }


def group_facts(
    *,
    row: AdSet,
    hours: float,
    figures: dict[str, int],
    kind: Outcome,
    ads: set[str],
    blocked: bool,
    usual_cost_minor: int | None = None,
) -> WatchedGroup:
    """One group as the watch decides on it: its money, results and state."""
    column = RESULT_COLUMNS.get(kind)
    results: int | None = None
    if column is not None:
        results = figures.get(column, 0)
        if kind == "lead":
            results = max(results, figures.get("ours_leads", 0))
    own = row.daily_budget_minor or None
    shared_budget = row.campaign.daily_budget_minor if row.campaign_id else None
    switched_off = bool(ads) and ads <= {Delivery.PAUSED}
    ads = ads - {Delivery.PAUSED}
    refused = row.delivery == Delivery.REJECTED or (
        bool(ads) and ads <= {Delivery.REJECTED}
    )
    unpaid = row.delivery == Delivery.BILLING or (
        bool(ads) and ads <= {Delivery.BILLING}
    )
    return WatchedGroup(
        adset_id=row.external_id,
        hours=hours,
        spend_minor=figures.get("spend_minor", 0),
        results=results,
        daily_budget_minor=own or shared_budget or None,
        in_review=Delivery.ACTIVE not in ads
        and (Delivery.PENDING in ads or row.delivery == Delivery.PENDING),
        blocked=blocked or refused or switched_off or unpaid,
        owns_budget=own is not None,
        learning=row.is_learning,
        limited=(row.learning_status or "").upper() in LEARNING_LIMITED,
        impressions=figures.get("impressions", 0),
        link_clicks=figures.get("inline_link_clicks", 0),
        usual_cost_minor=usual_cost_minor,
    )


def ad_states(db: Session, *, owner: User, adset_ids: list[str]) -> dict[str, set[str]]:
    """``{group id: its adverts' delivery states}``, switched-off ones too."""
    states: dict[str, set[str]] = {}
    if not adset_ids:
        return states
    rows = db.execute(
        select(AdSet.external_id, Ad.delivery)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .where(Ad.owner_id == owner.id, AdSet.external_id.in_(adset_ids))
    )
    for adset_id, delivery in rows:
        states.setdefault(adset_id, set()).add(delivery)
    return states


__all__ = ["ad_states", "group_facts", "since_born", "today_so_far"]
