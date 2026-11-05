"""Writing the plans.

A plan is read live: a change to its limits or its pages reaches every
subscription on it at once, and its price and period the next bill. The
trial runs on the default plan's limits too. A plan belongs to no customer,
so its journal row is filed under the member of staff who wrote it.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import PlanInUse
from app.modules.backoffice.selectors.plans import plan_is_used
from app.modules.backoffice.services.journal import record
from app.modules.billing.models import Plan

logger = logging.getLogger(__name__)

# The columns an office edit can move, with the label the journal shows.
TRACKED = {
    "code": "Kod",
    "name": "Nomi",
    "tagline": "Shior",
    "features": "Imkoniyatlar",
    "price": "Narxi",
    "period_days": "Muddati (kun)",
    "max_adsets": "Reklama limiti",
    "daily_chat_requests": "Kunlik AI savollar",
    "llm_cost_limit_minor": "Oylik AI xarajat chegarasi (sent)",
    "included_pages": "Sahifalar",
    "included_google_accounts": "Google akkauntlar",
    "extra_page_price": "Qo'shimcha sahifa narxi",
    "crm_seat_price": "CRM menejer o'rni narxi",
    "is_one_time": "Bir martalik",
    "is_active": "Sotuvda",
    "sort_order": "Tartib",
}


def plans_currency(db: Session) -> str:
    """The currency every plan is priced in: the one the plans already use."""
    return db.scalar(select(Plan.currency).limit(1)) or settings.billing_currency


def create_plan(db: Session, *, data: dict[str, Any], actor: User) -> Plan:
    row = Plan(**data, currency=plans_currency(db))
    db.add(row)
    db.flush()
    _journal(
        db,
        actor=actor,
        kind=ActionKind.PLAN_CREATED,
        plan=row,
        changed=_changes(before={}, after=_snapshot(row)),
    )
    logger.info("plan %s created by %s", row.code, actor.id)
    return row


def update_plan(db: Session, *, plan: Plan, data: dict[str, Any], actor: User) -> Plan:
    before = _snapshot(plan)
    for name, value in data.items():
        setattr(plan, name, value)
    db.flush()
    _journal(
        db,
        actor=actor,
        kind=ActionKind.PLAN_UPDATED,
        plan=plan,
        changed=_changes(before=before, after=_snapshot(plan)),
    )
    logger.info("plan %s updated by %s", plan.code, actor.id)
    return plan


def delete_plan(db: Session, *, plan: Plan, actor: User) -> None:
    """Delete a plan nothing points at; a used one is taken off sale instead."""
    if plan_is_used(db, plan=plan):
        raise PlanInUse
    _journal(db, actor=actor, kind=ActionKind.PLAN_DELETED, plan=plan, changed={})
    db.delete(plan)
    db.flush()
    logger.info("plan %s deleted by %s", plan.code, actor.id)


def _snapshot(row: Plan) -> dict[str, str]:
    """The tracked columns as the text a colleague reads in the journal."""
    return {name: str(getattr(row, name)) for name in TRACKED}


def _changes(*, before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """Each column that moved, under its own label, as [was, now]."""
    return {
        label: [before.get(name, ""), after[name]]
        for name, label in TRACKED.items()
        if before.get(name, "") != after[name]
    }


def _journal(
    db: Session,
    *,
    actor: User,
    kind: ActionKind,
    plan: Plan,
    changed: dict[str, list[str]],
) -> None:
    record(
        db,
        customer=actor,
        actor=actor,
        kind=kind,
        detail={"code": plan.code, "changed": changed},
    )
