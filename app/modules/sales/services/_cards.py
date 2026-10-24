"""What every move of a card shares: the lock, the office journal, the trail."""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.backoffice.constants import ActionKind
from app.modules.sales.constants import WS_GROUP, ActivityKind
from app.modules.sales.exceptions import CardClosed, NotYourCard
from app.modules.sales.models import ContactHold, LostReason, SalesActivity, SalesClaim
from app.modules.sales.selectors.search import subject_q

logger = logging.getLogger(__name__)
AGGREGATE = "sales_claim"
CLOSE_FIELDS = ("closed_at", "outcome")


def card_event(*, client_id: uuid.UUID | str) -> dict[str, str]:
    return {"type": "board.card", "client": str(client_id)}


def announce(db: Session, *, client_id: uuid.UUID | str | None) -> None:
    """Tell open boards a card changed, once the change is committed.

    Django sent this through a channels group; here it is a Redis publish on
    the same channel name, which a websocket gateway relays. Without Redis
    the board just refreshes on its own timer.
    """
    if client_id is None:
        return
    on_commit(db, lambda: _send(client_id=client_id))


def _send(*, client_id: uuid.UUID | str) -> None:
    import json

    from app.common.cache import cache

    try:
        cache.publish(WS_GROUP, json.dumps(card_event(client_id=client_id)))
    except Exception as exc:
        logger.warning("sales board announce failed: %s", exc)


def locked_card(db: Session, *, client_id: uuid.UUID, manager: User) -> SalesClaim:
    claim = db.scalars(
        select(SalesClaim)
        .where(subject_q(SalesClaim, client_id), SalesClaim.closed_at.is_(None))
        .with_for_update()
        .limit(1)
    ).first()
    if claim is None:
        raise CardClosed
    if claim.manager_id != manager.id:
        raise NotYourCard
    return claim


def journal(
    db: Session, *, claim: SalesClaim, actor: User, kind: ActionKind, **fields: Any
) -> None:
    from app.modules.backoffice.services import record

    if claim.owner is not None:
        record(db, customer=claim.owner, actor=actor, kind=kind, **fields)


def trail(
    db: Session,
    *,
    claim: SalesClaim,
    actor: User | None,
    kind: ActivityKind,
    now: datetime,
    reason: LostReason | None = None,
    body: str = "",
    callback_at: datetime | None = None,
    event: EventName = EventName.SALES_CARD_MOVED,
    payload: dict[str, Any] | None = None,
) -> SalesActivity:
    line = SalesActivity(
        owner_id=claim.owner_id,
        consult_id=claim.consult_id,
        claim_id=claim.id,
        actor_id=actor.id if actor else None,
        kind=str(kind),
        reason_id=reason.id if reason else None,
        body=body.strip(),
        callback_at=callback_at,
        created_at=now,
    )
    db.add(line)
    db.flush()
    if claim.owner_id is not None:
        emit(
            db,
            owner_id=claim.owner_id,
            name=event,
            aggregate_type=AGGREGATE,
            aggregate_id=claim.id,
            payload={
                "kind": str(kind),
                "stage": str(claim.stage),
                "outcome": str(claim.outcome),
                "manager_id": str(claim.manager_id or ""),
                **(payload or {}),
            },
            occurred_at=now,
        )
    announce(db, client_id=claim.subject_id)
    return line


def close(
    db: Session,
    *,
    claim: SalesClaim,
    outcome: str,
    now: datetime,
    reason: LostReason | None = None,
) -> None:
    claim.closed_at = now
    claim.outcome = str(outcome)
    if reason is not None:
        claim.reason_id = reason.id
    db.flush()


def hold(
    db: Session,
    *,
    claim: SalesClaim,
    until: datetime | None,
    set_by: User | None,
    reason: LostReason | None,
    now: datetime,
) -> ContactHold:
    if claim.owner_id is None and claim.consult_id is not None and set_by:
        from app.modules.public.services import mark_consult_contacted

        mark_consult_contacted(db, consult_id=claim.consult_id, actor=set_by, now=now)
    row = ContactHold(
        owner_id=claim.owner_id,
        consult_id=claim.consult_id,
        claim_id=claim.id,
        set_by_id=set_by.id if set_by else None,
        reason_id=reason.id if reason else None,
        until=until,
    )
    db.add(row)
    db.flush()
    return row
