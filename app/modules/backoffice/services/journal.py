import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import VIEW_QUIET_MINUTES, ActionKind
from app.modules.backoffice.models import StaffAction

logger = logging.getLogger(__name__)


def record(
    db: Session,
    *,
    customer: User,
    actor: User,
    kind: ActionKind,
    reason: str = "",
    detail: dict[str, Any] | None = None,
) -> StaffAction:
    row = StaffAction(
        owner_id=customer.id,
        actor_id=actor.id,
        kind=str(kind),
        reason=reason.strip(),
        detail=detail or {},
    )
    db.add(row)
    db.flush()
    return row


def seen(
    db: Session, *, customer: User, actor: User, kind: ActionKind = ActionKind.VIEW
) -> None:
    since = utcnow() - timedelta(minutes=VIEW_QUIET_MINUTES)
    recent = db.scalar(
        select(StaffAction.id)
        .where(
            StaffAction.owner_id == customer.id,
            StaffAction.actor_id == actor.id,
            StaffAction.kind == str(kind),
            StaffAction.created_at >= since,
        )
        .limit(1)
    )
    if recent is not None:
        return
    record(db, customer=customer, actor=actor, kind=kind)
    logger.info(
        "backoffice read recorded",
        extra={
            "customer_id": str(customer.id),
            "actor_id": str(actor.id),
            "kind": str(kind),
        },
    )
