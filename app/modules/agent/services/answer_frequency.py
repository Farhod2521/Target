"""The owner saying a frequency alert's advert is working well."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.constants import FrequencyAnswer, FrequencyLevel
from app.modules.agent.exceptions import FrequencyAlertGone
from app.modules.agent.models import FrequencyAlert
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

HIDDEN_FOR = timedelta(hours=24)


def answer_working_well(
    db: Session, *, user: User, alert_id: str, now: datetime
) -> FrequencyAlert:
    """Keep the answer. The next message comes only at the next level - or,
    at the last one, after a day. Caller commits."""
    try:
        pk = uuid.UUID(str(alert_id))
    except ValueError:
        raise FrequencyAlertGone from None
    row = db.scalar(
        select(FrequencyAlert)
        .where(
            FrequencyAlert.owner_id == user.id,
            FrequencyAlert.id == pk,
            FrequencyAlert.closed_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise FrequencyAlertGone
    row.answer, row.answered_at = FrequencyAnswer.WORKING_WELL, now
    if row.level == FrequencyLevel.REQUIRED:
        row.hidden_until = now + HIDDEN_FOR
    db.flush()
    emit(
        db,
        owner_id=user.id,
        name=EventName.FREQUENCY_ANSWERED,
        aggregate_type="adset",
        aggregate_id=row.adset_external_id,
        payload={"level": row.level, "answer": row.answer},
    )
    return row


__all__ = ["answer_working_well"]
