import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

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
    event = Event(
        owner_id=owner_id,
        name=str(name),
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=payload or {},
        occurred_at=occurred_at or utcnow(),
    )
    db.add(event)
    return event
