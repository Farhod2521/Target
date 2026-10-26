"""Every delivering group's last seven days, as the frequency levels read them."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import Delivery
from app.modules.ads.models import Ad, AdSet
from app.modules.agent.constants import FrequencyAnswer, FrequencyLevel
from app.modules.agent.models import FrequencyAlert
from app.modules.agent.selectors.facts import account_facts
from app.modules.agent.selectors.pair_views import pair_views
from app.modules.agent.selectors.policy import policy_for
from app.modules.agent.selectors.same_day import RESULT_COLUMNS, adset_sums, kind_of
from app.modules.agent.selectors.week_frequency import DAYS, week_readings
from app.modules.integrations.models import AdAccount
from core.agent import AdSetFacts, Policy
from core.agent.benchmark import count_in, family_of, peers, result_cost
from core.agent.frequency import RANK, Reading
from core.metrics import counted_leads, measured

_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One delivering group, its seven days, and the figures a message quotes."""

    account: AdAccount
    name: str
    reading: Reading
    ctr_before_bp: int | None
    ctr_now_bp: int | None
    cost_minor: int | None
    cost_usual_minor: int | None


def frequency_candidates(db: Session, *, owner: User, now: datetime) -> list[Candidate]:
    """Every delivering group of the subscription's pairs, once each."""
    from app.modules.ads.selectors.pages import page_scope
    from app.modules.integrations.selectors.slots import enabled_ad_accounts

    row = policy_for(db, owner=owner)
    policy = row.as_policy() if row is not None else Policy()
    accounts = enabled_ad_accounts(db, owner=owner)
    whole = page_scope(db, owner=owner)
    views = pair_views(db, owner=owner, whole=whole, accounts=accounts)
    reads = (
        [(view.scope, account) for view in views for account in view.accounts]
        if views
        else [(whole, account) for account in accounts]
    )
    found: dict[str, Candidate] = {}
    for scope, account in reads:
        facts = account_facts(
            db, owner=owner, account=account, policy=policy, now=now, scope=scope
        )
        live = [
            item for item in facts.adsets if item.delivery == _ACTIVE and item.is_ours
        ]
        week = week_readings(
            db,
            owner=owner,
            account=account,
            adset_ids=[item.external_id for item in live],
        )
        for item in live:
            if item.external_id in found or item.external_id not in week:
                continue
            usual = peers(facts.adsets, item, facts.usual).cost_minor
            found[item.external_id] = Candidate(
                account=account,
                name=item.name,
                reading=week[item.external_id],
                ctr_before_bp=item.launch_ctr_bp,
                ctr_now_bp=item.recent.link_ctr_bp,
                cost_minor=_cost(item),
                cost_usual_minor=usual,
            )
    return list(found.values())


def alerts_to_show(
    db: Session, *, owner: User, now: datetime, hidden_adsets: Collection[str] = ()
) -> list[FrequencyAlert]:
    """The open levels still waiting for an answer, highest first."""
    a = FrequencyAlert
    rows = db.scalars(
        select(a).where(
            a.owner_id == owner.id,
            a.closed_at.is_(None),
            or_(
                a.answer == "",
                and_(
                    a.level == FrequencyLevel.REQUIRED,
                    a.answer == FrequencyAnswer.WORKING_WELL,
                    a.hidden_until <= now,
                ),
            ),
            a.adset_external_id.not_in(list(hidden_adsets)),
        )
    )
    return sorted(rows, key=lambda row: (-RANK[row.level], row.created_at))


def has_pressing_alerts(db: Session, *, owner: User) -> bool:
    """Whether any warning or required level is open. One indexed read."""
    a = FrequencyAlert
    return (
        db.scalar(
            select(a.id)
            .where(
                a.owner_id == owner.id,
                a.closed_at.is_(None),
                a.level.in_([FrequencyLevel.WARNING, FrequencyLevel.REQUIRED]),
            )
            .limit(1)
        )
        is not None
    )


def creative_target(db: Session, *, owner: User, adset_id: str) -> str:
    """A delivering advert of the group to add a creative beside, or ``""``."""
    return (
        db.scalar(
            select(Ad.external_id)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(
                Ad.owner_id == owner.id,
                AdSet.external_id == adset_id,
                Ad.delivery == Delivery.ACTIVE,
            )
            .order_by(Ad.created_at.desc())
            .limit(1)
        )
        or ""
    )


def newest_ads(
    db: Session, *, owner: User, adset_ids: list[str]
) -> dict[str, datetime]:
    """``{group: when its newest advert first reached the mirror}``."""
    if not adset_ids:
        return {}
    rows = db.execute(
        select(AdSet.external_id, func.max(Ad.created_at))
        .join(AdSet, AdSet.id == Ad.adset_id)
        .where(Ad.owner_id == owner.id, AdSet.external_id.in_(adset_ids))
        .group_by(AdSet.external_id)
    )
    return {adset_id: newest for adset_id, newest in rows if newest is not None}


def cost_between(
    db: Session,
    *,
    owner: User,
    account: AdAccount,
    adset_id: str,
    since: datetime,
    until: datetime,
) -> int | None:
    """What one of a group's results cost between two moments, or nothing."""
    from app.modules.leads.selectors import counts_by_adset

    goal = db.execute(
        select(AdSet.optimization_goal_raw, AdSet.promoted_object_raw).where(
            AdSet.owner_id == owner.id, AdSet.external_id == adset_id
        )
    ).first()
    kind = kind_of(goal[0], goal[1]) if goal else kind_of("")
    column = RESULT_COLUMNS.get(kind)
    if column is None:
        return None
    tzinfo = account.tzinfo()
    figures = adset_sums(
        db,
        owner=owner,
        account=account,
        since=since.astimezone(tzinfo).date(),
        until=until.astimezone(tzinfo).date(),
    ).get(adset_id, {})
    count = int(figures.get(column, 0))
    spend = int(figures.get("spend_minor", 0))
    if kind == "lead":
        ours = counts_by_adset(db, owner=owner, since=since, until=until)
        count = counted_leads(
            ours=ours.get(adset_id, (0, 0))[0],
            reported=count,
            measured=measured(
                spend_minor=spend,
                impressions=int(figures.get("impressions", 0)),
                reported=count,
            ),
        )
    return round(spend / count) if count else None


def _cost(item: AdSetFacts) -> int | None:
    """What one of its results cost over the night's window."""
    family = family_of(item)
    return result_cost(
        spend_minor=item.totals.spend_minor,
        count=count_in(
            totals=item.totals, link_clicks=item.funnel.link_clicks, family=family
        ),
        family=family,
    )


__all__ = [
    "DAYS",
    "Candidate",
    "alerts_to_show",
    "cost_between",
    "creative_target",
    "frequency_candidates",
    "has_pressing_alerts",
    "newest_ads",
]
