"""The owner's answer to a price rise (TZ 1.5): stop the group, or watch it."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.agent.constants import PRICE_QUIET_HOURS, PriceAnswer
from app.modules.agent.exceptions import PriceAlertGone
from app.modules.agent.models import PriceAlert
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit


def open_price_alert(db: Session, *, user: User, alert_id: str) -> PriceAlert:
    """One of the owner's open price rises, locked. Raises when it is gone."""
    try:
        pk = uuid.UUID(str(alert_id))
    except ValueError:
        raise PriceAlertGone from None
    row = db.scalar(
        select(PriceAlert)
        .where(
            PriceAlert.owner_id == user.id,
            PriceAlert.id == pk,
            PriceAlert.closed_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise PriceAlertGone
    return row


def answer_watching(
    db: Session, *, user: User, alert_id: str, now: datetime
) -> PriceAlert:
    """«Kuzataman»: kept, and nothing more about the group for 72 hours. A
    frequency level of the same group said in the same message is answered
    with it - both say "leave it running". Caller commits."""
    row = open_price_alert(db, user=user, alert_id=alert_id)
    _answer(db, user=user, row=row, answer=PriceAnswer.WATCHING, now=now)
    _frequency_answered(db, user=user, row=row, now=now)
    return row


def answer_pause(
    db: Session, *, user: User, alert_id: str, now: datetime
) -> PriceAlert:
    """«Reklamani to'xtatish»: the group is paused - only ever on this press
    (TZ 1.5). Caller commits."""
    row = open_price_alert(db, user=user, alert_id=alert_id)
    actions.request(
        db,
        user=user,
        ask=actions.Pause(level=ManagedLevel.ADSET, external_id=row.adset_external_id),
    )
    _answer(db, user=user, row=row, answer=PriceAnswer.PAUSED, now=now)
    return row


def _answer(
    db: Session, *, user: User, row: PriceAlert, answer: str, now: datetime
) -> None:
    row.answer, row.answered_at = answer, now
    db.flush()
    emit(
        db,
        owner_id=user.id,
        name=EventName.PRICE_ANSWERED,
        aggregate_type="adset",
        aggregate_id=row.adset_external_id,
        payload={"answer": answer},
    )


def _frequency_answered(
    db: Session, *, user: User, row: PriceAlert, now: datetime
) -> None:
    from app.modules.agent.selectors.price_alerts import merged_frequency

    level = merged_frequency(db, row=row)
    if level is None or level.answer:
        return
    from app.modules.agent.services.answer_frequency import answer_working_well

    answered = answer_working_well(db, user=user, alert_id=str(level.id), now=now)
    if answered.hidden_until is not None:
        # The price's 72 quiet hours, not the frequency's own day.
        answered.hidden_until = max(
            answered.hidden_until, now + timedelta(hours=PRICE_QUIET_HOURS)
        )
        db.flush()


__all__ = ["answer_pause", "answer_watching", "open_price_alert"]
