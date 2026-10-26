"""The groups the agent may stop by itself, with what they spent and brought."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import Delivery, LaunchStep
from app.modules.ads.models import AdSet, CampaignLaunch
from app.modules.agent.constants import AUTO_STOP_FRESH_MINUTES, AUTO_STOP_MARK
from app.modules.agent.selectors.launch_watch import switched_on
from app.modules.agent.selectors.same_day import (
    RESULT_COLUMNS,
    TODAY_KINDS,
    adset_sums,
    group_usuals,
    kind_of,
)
from app.modules.agent.selectors.stopped_watch import last_stops
from app.modules.agent.selectors.window import start_of
from app.modules.integrations.models import AdAccount
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent.auto_stop import Fruitless
from core.metrics import Outcome, heard_leads


@dataclass(frozen=True, slots=True)
class StopCandidate:
    """One group as the rule reads it, and its totals for the audit row."""

    group: Fruitless
    spent_ever_minor: int
    results_ever: int
    currency: str
    impressions_ever: int = 0
    link_clicks_ever: int = 0


def stop_candidates(db: Session, *, owner: User, now: datetime) -> list[StopCandidate]:
    """Every delivering group launched here, on accounts with fresh figures."""
    from app.modules.integrations.selectors.pairs import stored_pairs
    from app.modules.integrations.selectors.slots import enabled_pages

    pairs = stored_pairs(db, owner=owner, pages=enabled_pages(db, owner=owner))
    stored = {(pair.page.id, pair.account.id) for pair in pairs}
    found: list[StopCandidate] = []
    accounts = db.scalars(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id, AdAccount.is_active.is_(True)
        )
    )
    for account in accounts:
        if _fresh(db, owner=owner, account=account, now=now):
            off = _off_pair(db, owner=owner, account=account, stored=stored)
            found += [
                candidate
                for candidate in _account_candidates(
                    db, owner=owner, account=account, now=now
                )
                if candidate.group.adset_id not in off
            ]
    return found


def _off_pair(
    db: Session, *, owner: User, account: AdAccount, stored: set[tuple[UUID, UUID]]
) -> set[str]:
    """The groups this account's launches made for pages not paired with it."""
    confirmed = {page for page, _account in stored}
    off: set[str] = set()
    rows = db.execute(
        select(CampaignLaunch.page_id, CampaignLaunch.created_refs).where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.ad_account_id == account.id,
            CampaignLaunch.page_id.in_(confirmed),
        )
    )
    for page_id, created_refs in rows:
        if (page_id, account.id) not in stored:
            off.update(ref_field.ref_ids(created_refs, LaunchStep.ADSET))
    return off


def _fresh(db: Session, *, owner: User, account: AdAccount, now: datetime) -> bool:
    since = now - timedelta(minutes=AUTO_STOP_FRESH_MINUTES)
    if account.synced_at is None or account.synced_at < since:
        return False
    today = now.astimezone(account.tzinfo()).date()
    newest = db.scalar(
        select(func.max(MetricsDaily.synced_at)).where(
            *cabinet_where(db, owner=owner, account=account),
            MetricsDaily.date == today,
        )
    )
    return newest is not None and newest >= since


def _account_candidates(
    db: Session, *, owner: User, account: AdAccount, now: datetime
) -> list[StopCandidate]:
    from app.modules.leads.selectors import counts_by_adset

    born = switched_on(db, owner=owner, account=account)
    groups = [
        row
        for row in db.scalars(
            select(AdSet).where(
                AdSet.owner_id == owner.id,
                AdSet.external_id.in_(list(born)),
                AdSet.delivery == Delivery.ACTIVE,
            )
        )
        if kind_of(row.optimization_goal_raw, row.promoted_object_raw) in TODAY_KINDS
    ]
    if not groups:
        return []
    tzinfo = account.tzinfo()
    first = min(born[row.external_id] for row in groups).astimezone(tzinfo)
    sums = adset_sums(
        db,
        owner=owner,
        account=account,
        since=first.date(),
        until=now.astimezone(tzinfo).date(),
    )
    ours = counts_by_adset(
        db, owner=owner, since=start_of(first.date(), tzinfo), until=now
    )
    ids = [row.external_id for row in groups]
    stops = last_stops(db, owner=owner, adset_ids=ids)
    usual = group_usuals(db, owner=owner, account=account, adset_ids=ids)
    found: list[StopCandidate] = []
    for row in groups:
        figures = sums.get(row.external_id, {})
        kind = kind_of(row.optimization_goal_raw, row.promoted_object_raw)
        spent = figures.get("spend_minor", 0)
        results = _results(kind, figures, ours.get(row.external_id, (0, 0))[0])
        shown = figures.get("impressions", 0)
        clicks = figures.get("inline_link_clicks", 0)
        stop = stops.get(row.external_id)
        mark = (stop.request_payload or {}).get(AUTO_STOP_MARK, {}) if stop else {}
        group = Fruitless(
            adset_id=row.external_id,
            spend_minor=spent - mark.get("spend_minor", 0),
            results=results - mark.get("results", 0),
            budget_minor=_budget(row),
            impressions=shown - mark.get("impressions", 0),
            link_clicks=clicks - mark.get("link_clicks", 0),
            usual_cost_minor=usual(row.external_id, kind),
        )
        found.append(
            StopCandidate(
                group=group,
                spent_ever_minor=spent,
                results_ever=results,
                currency=account.currency,
                impressions_ever=shown,
                link_clicks_ever=clicks,
            )
        )
    return found


def _results(kind: Outcome, figures: dict[str, int], ours: int) -> int:
    """A lead either side has seen, or the provider's count of the kind."""
    if kind == "lead":
        reported = max(
            figures.get("leads_reported", 0), figures.get("results_reported", 0)
        )
        return heard_leads(ours=ours, reported=reported)
    return figures.get(RESULT_COLUMNS[kind], 0)


def _budget(row: AdSet) -> int:
    """The day's budget: the group's own, else its campaign's shared one."""
    shared = row.campaign.daily_budget_minor if row.campaign_id else 0
    return row.daily_budget_minor or shared or 0


__all__ = ["StopCandidate", "stop_candidates"]
