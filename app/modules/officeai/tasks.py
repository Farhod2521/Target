"""The office assistant's workers: answer a turn, close the stuck ones."""

from datetime import timedelta

from sqlalchemy import update

from app.common.db import utcnow
from app.worker import celery_app, task_session


@celery_app.task(queue="chat", ignore_result=True)
def answer_office_turn(turn_id: str) -> None:
    from app.modules.officeai.services.answer import answer_turn
    from app.modules.officeai.services.ask import turn_payload

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        return
    with task_session() as db:
        answer_turn(db, turn_id=turn_id, payload=payload, now=utcnow())
        db.commit()


@celery_app.task(queue="sync", ignore_result=True)
def sweep_stuck_office_answers() -> int:
    """An answer whose worker died would stay "pending" for ever."""
    from app.modules.officeai.constants import (
        ANSWER_STUCK_AFTER_MINUTES,
        Author,
        MessageStatus,
    )
    from app.modules.officeai.models import OfficeAiMessage

    now = utcnow()
    with task_session() as db:
        closed = db.execute(
            update(OfficeAiMessage)
            .where(
                OfficeAiMessage.author == Author.AI,
                OfficeAiMessage.status == MessageStatus.PENDING,
                OfficeAiMessage.created_at
                < now - timedelta(minutes=ANSWER_STUCK_AFTER_MINUTES),
            )
            .values(status=MessageStatus.FAILED, updated_at=now)
        ).rowcount  # type: ignore[attr-defined]
        db.commit()
    return int(closed or 0)


__all__ = ["answer_office_turn", "sweep_stuck_office_answers"]
