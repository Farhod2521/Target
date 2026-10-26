"""One account, assembled for the playbook."""

from datetime import date, datetime, timedelta
from typing import cast

from metaads import PROVIDER as META
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import draft as draft_field
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import Delivery, DraftSection, LaunchStatus
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.selectors.window import yesterday
from app.modules.integrations.models import (
    AdAccount,
    CustomAudience,
    PageAccount,
    PixelAccount,
)
from app.modules.leads.models import LeadForm
from app.modules.metrics.constants import MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.facts import cabinet_where
from core.agent import Policy
from core.metrics import counts_leads
from core.strategy import (
    SIGNAL_WINDOW_DAYS,
    AdSetPosture,
    AudienceAssets,
    SignalHistory,
    StrategyState,
    has_exited_learning,
    stage,
)
from core.targeting import MODES, PLACEMENT_MODES, PlacementMode, TargetingMode

_ADSET_STEP = "adset"


def strategy_state(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    policy: Policy,
    now: datetime,
    window_days: int = SIGNAL_WINDOW_DAYS,
    scope: PageScope | None = None,
) -> StrategyState:
    """Everything the playbook is allowed to look at, in one value."""
    until = yesterday(tzinfo=account.tzinfo(), now=now)
    since = until - timedelta(days=window_days - 1)
    figures = _figures_by_adset(db, owner=owner, since=since, until=until)
    ads = _active_ads(db, owner=owner)
    modes = _chosen_modes(db, owner=owner)
    postures: list[AdSetPosture] = []
    reported = 0
    proven = False
    rows = db.scalars(
        select(AdSet)
        .where(AdSet.owner_id == owner.id, AdSet.provider == META)
        .order_by(AdSet.external_id)
    )
    for row in rows:
        if scope is not None and row.external_id in scope.outside:
            continue
        posture = _posture(
            row=row,
            figures=figures.get(row.external_id, {}),
            creatives=ads.get(row.external_id, 0),
            modes=modes.get(row.external_id, (None, None)),
            policy=policy,
            now=now,
        )
        postures.append(posture)
        if posture.counts_leads:
            reported += int(figures.get(row.external_id, {}).get("leads_reported", 0))
        proven = proven or has_exited_learning(row.learning_status)
    history = SignalHistory(
        window_days=window_days,
        reported_results=reported,
        days_with_spend=_days_with_spend(
            db, owner=owner, since=since, until=until, scope=scope
        ),
        has_proven_adset=proven,
    )
    blocked = list(scope.blocked) if scope is not None else []
    active = db.scalar(
        select(func.count(Campaign.id)).where(
            Campaign.owner_id == owner.id,
            Campaign.provider == META,
            Campaign.delivery == Delivery.ACTIVE,
            Campaign.external_id.not_in(blocked),
        )
    )
    return StrategyState(
        history=history,
        assets=_assets(db, owner=owner),
        adsets=tuple(postures),
        active_campaigns=int(active or 0),
    )


def _posture(
    *,
    row: AdSet,
    figures: dict[str, int],
    creatives: int,
    modes: tuple[TargetingMode | None, PlacementMode | None],
    policy: Policy,
    now: datetime,
) -> AdSetPosture:
    """One mirror row, reduced to what a strategy reads off it."""
    age_hours: int | None = None
    if row.start_time is not None:
        age_hours = max(0, int((now - row.start_time).total_seconds() // 3600))
    mode, placement = modes
    return AdSetPosture(
        external_id=row.external_id,
        stage=stage(
            age_hours=age_hours,
            is_learning=row.is_learning,
            learning_status=row.learning_status,
            days_with_spend=int(figures.get("days", 0)),
            test_hours=policy.test_hours,
            min_days=policy.min_days,
        ),
        delivery=str(row.delivery),
        counts_leads=counts_leads(row.optimization_goal_raw),
        creatives=creatives,
        mode=mode,
        placement=placement,
    )


def _figures_by_adset(
    db: Session, *, owner: User, since: date, until: date
) -> dict[str, dict[str, int]]:
    """``{ad set id: sums}`` over the season, from the provider's own days."""
    m = MetricsDaily
    rows = db.execute(
        select(
            m.adset_external_id,
            func.sum(m.leads_reported).label("leads_reported"),
            func.count(distinct(m.date)).label("days"),
        )
        .where(
            *cabinet_where(db, owner=owner, level=MetricLevel.ADSET),
            m.date >= since,
            m.date <= until,
            m.adset_external_id != "",
        )
        .group_by(m.adset_external_id)
    )
    return {
        row.adset_external_id: {
            "leads_reported": int(row.leads_reported or 0),
            "days": int(row.days or 0),
        }
        for row in rows
    }


def _days_with_spend(
    db: Session, *, owner: User, since: date, until: date, scope: PageScope | None
) -> int:
    """How many of the season's days anything at all was spent."""
    m = MetricsDaily
    outside = list(scope.outside) if scope is not None else []
    counted = db.scalar(
        select(func.count(distinct(m.date))).where(
            *cabinet_where(db, owner=owner, level=MetricLevel.ADSET),
            m.date >= since,
            m.date <= until,
            m.spend_minor > 0,
            m.adset_external_id.not_in(outside),
        )
    )
    return int(counted or 0)


def _active_ads(db: Session, *, owner: User) -> dict[str, int]:
    """``{ad set id: delivering ads}`` - the creative test's denominator."""
    rows = db.execute(
        select(AdSet.external_id, func.count(Ad.id))
        .join(AdSet, AdSet.id == Ad.adset_id)
        .where(
            Ad.owner_id == owner.id,
            Ad.provider == META,
            Ad.delivery == Delivery.ACTIVE,
            AdSet.external_id != "",
        )
        .group_by(AdSet.external_id)
    )
    return {external_id: int(count) for external_id, count in rows}


def _chosen_modes(
    db: Session, *, owner: User
) -> dict[str, tuple[TargetingMode | None, PlacementMode | None]]:
    """``{ad set id: (targeting mode, placement mode)}`` for our launches."""
    found: dict[str, tuple[TargetingMode | None, PlacementMode | None]] = {}
    rows = db.execute(
        select(CampaignLaunch.draft, CampaignLaunch.created_refs).where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.status == LaunchStatus.CREATED,
        )
    )
    for draft, created_refs in rows:
        audience = draft_field.chosen(draft, DraftSection.AUDIENCE)
        if not isinstance(audience, dict):
            continue
        mode = audience.get("targeting_mode")
        placement = audience.get("placement_mode")
        pair = (
            cast(TargetingMode, mode) if mode in MODES else None,
            cast(PlacementMode, placement) if placement in PLACEMENT_MODES else None,
        )
        for external_id in ref_field.ref_ids(created_refs, _ADSET_STEP):
            found[external_id] = pair
    return found


def _assets(db: Session, *, owner: User) -> AudienceAssets:
    """What the audience mirror holds, counted the playbook's way."""
    lookalikes = seeds = retargeting = 0
    for row in db.scalars(
        select(CustomAudience).where(CustomAudience.owner_id == owner.id)
    ):
        is_lookalike = bool(row.breadth) or bool(row.lookalike_raw)
        lookalikes += is_lookalike
        seeds += bool(row.can_seed and row.is_ready and row.approximate_count_upper > 0)
        retargeting += (
            bool(row.source_kind) or bool(row.rule_raw)
        ) and not is_lookalike
    return AudienceAssets(
        ready_seeds=seeds,
        lookalikes=lookalikes,
        retargeting=retargeting,
        has_traffic_source=_has_traffic_source(db, owner=owner),
    )


def _has_traffic_source(db: Session, *, owner: User) -> bool:
    """Whether anything exists to build a retargeting audience from."""
    return any(
        db.scalar(select(model.id).where(model.owner_id == owner.id).limit(1))
        is not None
        for model in (PixelAccount, PageAccount, LeadForm)
    )


__all__ = ["strategy_state"]
