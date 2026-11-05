"""The plans as the office reads them, with who stands on each."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
from app.modules.billing.models import (
    Invoice,
    Plan,
    PromoCode,
    Subscription,
    SubscriptionChange,
)
from app.modules.billing.selectors.plans import every_plan
from app.modules.sales.models import SalesSegment
from app.modules.surveys.models.survey import surveys_plans


@dataclass(frozen=True, slots=True)
class PlanRow:
    plan: Plan
    live: int
    deletable: bool


def plan_rows(db: Session) -> list[PlanRow]:
    """Every plan, the withdrawn ones last, with its live subscriptions."""
    counts: dict[uuid.UUID, int] = {
        plan_id: count
        for plan_id, count in db.execute(
            select(Subscription.plan_id, func.count(Subscription.id))
            .where(Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES))
            .group_by(Subscription.plan_id)
        )
    }
    return [
        PlanRow(plan, counts.get(plan.id, 0), not plan_is_used(db, plan=plan))
        for plan in every_plan(db)
    ]


def live_on(db: Session, *, plan: Plan) -> int:
    return (
        db.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.plan_id == plan.id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )
        or 0
    )


def plan_by_id(db: Session, *, plan_id: uuid.UUID) -> Plan | None:
    return db.get(Plan, plan_id)


def plan_is_used(db: Session, *, plan: Plan) -> bool:
    """Whether anything at all points at the plan: a bill, a subscription old or
    live, a promo code, a change of plan, a sales segment or a survey."""
    pointers = (
        select(Subscription.id).where(Subscription.plan_id == plan.id),
        select(Invoice.id).where(Invoice.plan_id == plan.id),
        select(PromoCode.id).where(PromoCode.plan_id == plan.id),
        select(SubscriptionChange.id).where(
            (SubscriptionChange.from_plan_id == plan.id)
            | (SubscriptionChange.to_plan_id == plan.id)
        ),
        select(SalesSegment.id).where(SalesSegment.plan_id == plan.id),
        select(surveys_plans.c.id).where(surveys_plans.c.plan_id == plan.id),
    )
    return any(db.scalar(query.limit(1)) is not None for query in pointers)
