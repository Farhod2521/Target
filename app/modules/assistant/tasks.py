"""The one chat's workers: answer a turn, and close the ones that never came back."""

from datetime import timedelta

from sqlalchemy import update

from app.common.db import utcnow
from app.worker import celery_app, task_session


@celery_app.task(queue="chat", ignore_result=True)
def answer_assistant_turn(turn_id: str) -> None:
    from app.modules.assistant.services.answer import answer_turn
    from app.modules.assistant.services.ask import turn_payload

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        return
    with task_session() as db:
        answer_turn(db, turn_id=turn_id, payload=payload, now=utcnow())
        db.commit()


@celery_app.task(queue="sync", ignore_result=True)
def sweep_stuck_assistant_answers() -> int:
    """An answer whose worker died stays "pending" for ever otherwise."""
    from app.modules.assistant.constants import (
        ANSWER_STUCK_AFTER_MINUTES,
        Author,
        MessageStatus,
    )
    from app.modules.assistant.models import AssistantMessage

    now = utcnow()
    with task_session() as db:
        closed = db.execute(
            update(AssistantMessage)
            .where(
                AssistantMessage.author == Author.AI,
                AssistantMessage.status == MessageStatus.PENDING,
                AssistantMessage.created_at
                < now - timedelta(minutes=ANSWER_STUCK_AFTER_MINUTES),
            )
            .values(status=MessageStatus.FAILED, updated_at=now)
        ).rowcount
        db.commit()
    return int(closed or 0)


__all__ = ["answer_assistant_turn", "sweep_stuck_assistant_answers"]

# The support chat's hooks, registered wherever the chat's tasks are loaded.
from app.modules.assistant import listeners as _listeners  # noqa: E402, F401
