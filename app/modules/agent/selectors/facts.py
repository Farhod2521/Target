"""One account, assembled into something the rules can reason about."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import LEARNING_LIMITED
from app.modules.ads.models import AdSet, Campaign
from app.modules.ads.recommendations import meanings
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.selectors.account_reads import (
    Slices,
    Window,
    ads_by_adset,
    audiences_we_hold,
    junk_by_adset,
    landing_by_adset,
    launch_ctr_by_adset,
    recent_by_adset,
    slices_by_adset,
    sums_by_adset,
    unusable_in,
    usual_levels,
)
from app.modules.agent.selectors.pictures import own_pictures
from app.modules.agent.selectors.window import end_of, start_of, yesterday
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount
from app.modules.metrics.constants import BreakdownKind
from core.agent import AccountFacts, AdFacts, AdSetFacts, Landing, Policy, Recent
from core.metrics import (
    SegmentComparison,
    SegmentFigures,
    Totals,
    compare_segments,
    counts_leads,
    outcome_of,
)

LEVEL = "adset"


def account_facts(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    policy: Policy,
    now: datetime,
    scope: PageScope | None = None,
) -> AccountFacts:
    """Everything one night's decisions are made from."""
    from app.modules.ads.selectors import launched_campaign_ids, page_scope
    from app.modules.leads.selectors import counts_by_adset

    tzinfo = account.tzinfo()
    until = yesterday(tzinfo=tzinfo, now=now)
    since = until - timedelta(days=policy.window_days - 1)
    spend = sums_by_adset(db, owner=owner, since=since, until=until, account=account)
    leads = counts_by_adset(
        db, owner=owner, since=start_of(since, tzinfo), until=end_of(until, tzinfo)
    )
    stopped = _stopped_by_agent(db, owner=owner)
    moved = _budget_moved(db, owner=owner, since=start_of(since, tzinfo))
    slices = slices_by_adset(db, owner=owner, account=account, since=since, until=until)
    inside = ads_by_adset(db, owner=owner, account=account, since=since, until=until)
    landing = landing_by_adset(db, owner=owner, account=account)
    held = audiences_we_hold(db, owner=owner)
    ours = launched_campaign_ids(db, owner=owner, ad_account=account)

    outside = (scope or page_scope(db, owner=owner)).outside
    rows = [
        row
        for row in db.scalars(
            select(AdSet)
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .where(AdSet.owner_id == owner.id, _on(account))
            .order_by(AdSet.external_id)
        )
        if row.external_id not in outside
    ]
    ids = [row.external_id for row in rows]
    recent = recent_by_adset(
        db, owner=owner, account=account, adset_ids=ids, until=until
    )
    launch = launch_ctr_by_adset(db, owner=owner, account=account, adset_ids=ids)
    junk = junk_by_adset(
        db,
        owner=owner,
        adset_ids=ids,
        since=start_of(since, tzinfo),
        until=end_of(until, tzinfo),
    )
    adsets = tuple(
        replace(
            _adset(
                row=row,
                spend=spend,
                leads=leads,
                stopped=stopped,
                moved=moved,
                slices=slices,
                inside=inside,
                landing=landing,
                held=held,
                ours=ours,
            ),
            recent=recent.get(row.external_id) or Recent(),
            launch_ctr_bp=launch.get(row.external_id),
            junk_leads=junk.get(row.external_id, 0),
        )
        for row in rows
    )
    return AccountFacts(
        provider=account.provider,
        currency=account.currency,
        window_days=policy.window_days,
        totals=_totals(adsets),
        lead_totals=_lead_totals(adsets),
        adsets=adsets,
        library=own_pictures(db, owner=owner, account=account),
        usual=usual_levels(
            db,
            owner=owner,
            account=account,
            adsets=adsets,
            until=until,
            days=policy.usual_days,
        ),
    )


def _adset(
    *,
    row: AdSet,
    spend: dict[str, Window],
    leads: dict[str, tuple[int, int]],
    stopped: set[str],
    moved: set[str],
    slices: Slices,
    inside: dict[str, tuple[AdFacts, ...]],
    landing: dict[str, Landing],
    held: frozenset[str] | None,
    ours: frozenset[str],
) -> AdSetFacts:
    """One mirror row, joined to what it spent and what it brought in."""
    from app.modules.ads.selectors.actions import budget_floor

    figures = spend.get(row.external_id) or Window()
    counted, qualified = leads.get(row.external_id, (0, 0))
    cuts = slices.get(row.external_id, {})
    return AdSetFacts(
        external_id=row.external_id,
        campaign_external_id=row.campaign.external_id if row.campaign_id else "",
        name=row.name,
        delivery=str(row.delivery),
        totals=Totals(
            spend_minor=figures.spend_minor,
            impressions=figures.impressions,
            clicks=figures.clicks,
            leads=counted,
            qualified=qualified,
            leads_reported=figures.leads_reported,
            results=figures.results,
            recallers=figures.recallers,
            profile_visits=figures.profile_visits,
        ),
        days_with_spend=figures.days,
        is_learning=row.is_learning,
        learning_limited=row.learning_status.upper() in LEARNING_LIMITED,
        daily_budget_minor=row.daily_budget_minor,
        budget_moved=row.external_id in moved,
        targeting=row.targeting_raw or {},
        floor_minor=budget_floor(target=row, level=LEVEL),
        stopped_by_agent=row.external_id in stopped,
        early=figures.early,
        late=figures.late,
        segments=_age_cells(cuts),
        ads=inside.get(row.external_id, ()),
        counts_leads=counts_leads(row.optimization_goal_raw),
        outcome=outcome_of(row.optimization_goal_raw),
        is_ours=bool(row.campaign_id) and row.campaign.external_id in ours,
        issue_codes=tuple(str(code) for code in row.issue_codes or ()),
        unusable_audience_ids=unusable_in(targeting=row.targeting_raw, held=held),
        advice=meanings(row.recommendations or ()),
        funnel=figures.funnel,
        landing=landing.get(row.external_id) or Landing(),
        slices=cuts,
    )


def _age_cells(cuts: dict[str, tuple[SegmentFigures, ...]]) -> SegmentComparison:
    cells = cuts.get(BreakdownKind.AGE_GENDER)
    if not cells:
        return SegmentComparison()
    return compare_segments(list(cells))


def _stopped_by_agent(db: Session, *, owner: User) -> set[str]:
    """Objects whose most recent landed change was a stop we proposed."""
    latest: dict[str, tuple[str, str]] = {}
    rows = db.execute(
        select(ActionLog.target_external_id, ActionLog.action, ActionLog.actor_type)
        .where(
            ActionLog.owner_id == owner.id,
            ActionLog.target_level == LEVEL,
            ActionLog.status == ActionStatus.APPLIED,
            ActionLog.dry_run.is_(False),
        )
        .order_by(ActionLog.created_at.desc())
    )
    for external_id, action, actor in rows:
        latest.setdefault(external_id, (action, actor))
    return {
        external_id
        for external_id, (action, actor) in latest.items()
        if action == ActionType.PAUSE and actor == ActorType.AGENT
    }


def _budget_moved(db: Session, *, owner: User, since: datetime) -> set[str]:
    """Groups whose daily budget this product changed inside the window."""
    return set(
        db.scalars(
            select(ActionLog.target_external_id).where(
                ActionLog.owner_id == owner.id,
                ActionLog.target_level == LEVEL,
                ActionLog.action.in_((ActionType.BUDGET_UP, ActionType.BUDGET_DOWN)),
                ActionLog.status == ActionStatus.APPLIED,
                ActionLog.dry_run.is_(False),
                ActionLog.created_at >= since,
            )
        )
    )


def _on(account: AdAccount) -> ColumnElement[bool]:
    """The ad sets this account answers for."""
    if account.is_current:
        return or_(
            Campaign.ad_account_id == account.id, Campaign.ad_account_id.is_(None)
        )
    return Campaign.ad_account_id == account.id


def _lead_totals(adsets: Iterable[AdSetFacts]) -> Totals:
    """What a lead costs on this account, over the ad sets that can have one."""
    counted = [item for item in adsets if item.counts_leads]
    return Totals(
        spend_minor=sum(item.totals.spend_minor for item in counted),
        impressions=sum(item.totals.impressions for item in counted),
        clicks=sum(item.totals.clicks for item in counted),
        leads=sum(item.totals.leads for item in counted),
        qualified=sum(item.totals.qualified for item in counted),
        leads_reported=sum(item.totals.leads_reported for item in counted),
    )


def _totals(adsets: Iterable[AdSetFacts]) -> Totals:
    """What the account did over the window, across every ad set in it."""
    items = list(adsets)
    return Totals(
        spend_minor=sum(item.totals.spend_minor for item in items),
        impressions=sum(item.totals.impressions for item in items),
        clicks=sum(item.totals.clicks for item in items),
        leads=sum(item.totals.leads for item in items),
        qualified=sum(item.totals.qualified for item in items),
        leads_reported=sum(item.totals.leads_reported for item in items),
    )


__all__ = ["LEVEL", "account_facts"]
