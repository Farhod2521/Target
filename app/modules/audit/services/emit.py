import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.acting import acting_for
from app.common.db import utcnow
from app.modules.audit.models import Event


def emit(
    db: Session,
    *,
    owner_id: uuid.UUID | None,
    name: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID | str,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> Event:
    payload = dict(payload or {})
    held = acting_for(owner_id) if owner_id is not None else None
    if held is not None and held.by_member:
        # Done on the owner's behalf by a member of the business: who it was.
        payload.setdefault("acting_user_id", str(held.actor_id))
        payload.setdefault("business_id", str(held.business_id))
    event = Event(
        owner_id=owner_id,
        name=str(name),
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=payload,
        occurred_at=occurred_at or utcnow(),
    )
    db.add(event)
    return event
