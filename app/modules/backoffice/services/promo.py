"""Answering promo requests, and writing the promo catalogue.

The decision belongs to billing - which entitlement the days land on, what
the code reads as it stands now - and is not repeated here. What this adds
is the office's trace: who said yes, and what they wrote down.

A code's kind is set once, at creation, and never edited: an offer retyped
into another kind keeps whatever the old kind held, and that is how a
discount starts granting days. A code belongs to no customer, so its
journal row is filed under the member of staff who wrote it.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import PromoCodeInUse
from app.modules.backoffice.services.journal import record
from app.modules.billing.constants import PromoKind
from app.modules.billing.models import Plan, PromoCode, PromoRedemption
from app.modules.billing.services import approve_redemption, reject_redemption

logger = logging.getLogger(__name__)

# The columns an office edit can move, with the label the journal shows.
TRACKED = {
    "code": "Kod",
    "description": "Izoh",
    "is_active": "Faol",
    "starts_at": "Boshlanish vaqti",
    "expires_at": "Tugash vaqti",
    "max_uses": "Umumiy limit",
    "max_uses_per_user": "Bitta foydalanuvchiga",
    "note": "Ichki izoh",
    "grant_days": "Beriladigan kun",
    "plan": "Tarif",
    "grant_pages": "Beriladigan sahifa",
    "needs_approval": "Admin tasdig'i bilan",
    "discount_kind": "Chegirma turi",
    "discount_value": "Chegirma qiymati",
    "scope": "Qo'llanish sohasi",
    "min_amount_minor": "Eng kam summa",
}
SHARED = (
    "code",
    "description",
    "starts_at",
    "expires_at",
    "max_uses",
    "max_uses_per_user",
    "is_active",
    "note",
)
OWN = {
    PromoKind.PLAN: ("grant_days", "plan_id", "needs_approval"),
    PromoKind.SLOTS: ("grant_pages", "needs_approval"),
    PromoKind.DISCOUNT: (
        "discount_kind",
        "discount_value",
        "scope",
        "min_amount_minor",
    ),
}


def approve_promo(
    db: Session, *, redemption: PromoRedemption, actor: User, now: datetime
) -> PromoRedemption:
    """Hand over what the request asked for, and say who decided."""
    decided = approve_redemption(db, redemption=redemption, actor=actor, now=now)
    record(
        db,
        customer=decided.owner,
        actor=actor,
        kind=ActionKind.PROMO_APPROVED,
        detail={
            "code": decided.promo.code,
            "days": decided.granted_days,
            "pages": decided.granted_pages,
        },
    )
    return decided


def refuse_promo(
    db: Session,
    *,
    redemption: PromoRedemption,
    actor: User,
    reason: str,
    now: datetime,
) -> PromoRedemption:
    """Refuse the request, keeping the sentence that says why; billing
    checks the sentence, because its row carries it."""
    decided = reject_redemption(
        db, redemption=redemption, actor=actor, reason=reason, now=now
    )
    record(
        db,
        customer=decided.owner,
        actor=actor,
        kind=ActionKind.PROMO_REJECTED,
        reason=reason,
        detail={"code": decided.promo.code},
    )
    return decided


def create_code(
    db: Session, *, kind: PromoKind, data: dict[str, Any], actor: User
) -> PromoCode:
    """Write a new offer; the columns its kind does not use keep their
    defaults, which is what keeps a retyped row honest."""
    row = PromoCode(kind=str(kind), **_columns(kind=kind, data=data))
    db.add(row)
    db.flush()
    _journal(
        db,
        actor=actor,
        kind=ActionKind.PROMO_CODE_CREATED,
        code=row,
        changed=_changes(before={}, after=_snapshot(db, row)),
    )
    logger.info("promo code %s created by %s", row.code, actor.id)
    return row


def update_code(
    db: Session, *, code: PromoCode, data: dict[str, Any], actor: User
) -> PromoCode:
    """Rewrite this offer's figures, leaving its kind alone."""
    before = _snapshot(db, code)
    for name, value in _columns(kind=PromoKind(code.kind), data=data).items():
        setattr(code, name, value)
    db.flush()
    _journal(
        db,
        actor=actor,
        kind=ActionKind.PROMO_CODE_UPDATED,
        code=code,
        changed=_changes(before=before, after=_snapshot(db, code)),
    )
    logger.info("promo code %s updated by %s", code.code, actor.id)
    return code


def delete_code(db: Session, *, code: PromoCode, actor: User) -> None:
    """Delete an offer nobody has taken. Refused rather than cascaded when
    redemptions point at it: those rows are who took what."""
    taken = db.scalar(
        select(PromoRedemption.id).where(PromoRedemption.promo_id == code.id).limit(1)
    )
    if taken is not None:
        raise PromoCodeInUse
    _journal(db, actor=actor, kind=ActionKind.PROMO_CODE_DELETED, code=code, changed={})
    db.delete(code)
    db.flush()
    logger.info("promo code %s deleted by %s", code.code, actor.id)


def _columns(*, kind: PromoKind, data: dict[str, Any]) -> dict[str, Any]:
    """The columns one kind writes: the shared ones plus its own."""
    return {name: data[name] for name in (*SHARED, *OWN[kind]) if name in data}


def _snapshot(db: Session, row: PromoCode) -> dict[str, str]:
    """The tracked columns as the text a colleague reads in the journal."""
    plan = db.get(Plan, row.plan_id) if row.plan_id is not None else None
    shown = {name: _shown(getattr(row, name)) for name in TRACKED if name != "plan"}
    return shown | {"plan": plan.name if plan is not None else ""}


def _shown(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="minutes")
    return str(value)


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
    code: PromoCode,
    changed: dict[str, list[str]],
) -> None:
    record(
        db,
        customer=actor,
        actor=actor,
        kind=kind,
        detail={"code": code.code, "changed": changed},
    )
