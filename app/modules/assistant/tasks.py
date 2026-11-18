"""The one chat's workers: answer a turn, and close the ones that never came back."""

from datetime import timedelta

from sqlalchemy import update

from app.common.db import utcnow
from app.worker import celery_app, task_session


@celery_app.task(queue="chat", ignore_result=True)
def answer_assistant_turn(turn_id: str) -> None:
    from app.modules.assistant.services.answer import answer_turn, mark_failed
    from app.modules.assistant.services.ask import turn_payload

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        return
    with task_session() as db:
        try:
            answer_turn(db, turn_id=turn_id, payload=payload, now=utcnow())
        except Exception:
            # The row is closed now, not by the sweep twenty minutes on:
            # whatever the answer had written is dropped with the rollback.
            db.rollback()
            mark_failed(db, payload=payload)
            db.commit()
            raise
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


@celery_app.task(queue="agent", ignore_result=True)
def translate_refusal_task(
    answer_id: str, actor_id: str, source: str, targets: list[str]
) -> str:
    """The office's answer to a Meta refusal, in the other languages. With
    every other Claude call, and no retry: the office saves again."""
    from app.modules.assistant.services.translate import translate_refusal

    with task_session() as db:
        return translate_refusal(
            db, answer_id=answer_id, actor_id=actor_id, source=source, targets=targets
        )


@celery_app.task(queue="agent", ignore_result=True)
def translate_article_task(
    article_id: str, actor_id: str, source: str, targets: list[str]
) -> str:
    """A ready answer of the assistant's, in the other languages."""
    from app.modules.assistant.services.translate import translate_article

    with task_session() as db:
        return translate_article(
            db,
            article_id=article_id,
            actor_id=actor_id,
            source=source,
            targets=targets,
        )


__all__ = [
    "answer_assistant_turn",
    "sweep_stuck_assistant_answers",
    "translate_article_task",
    "translate_refusal_task",
]

# The support chat's hooks, registered wherever the chat's tasks are loaded.
from app.modules.assistant import listeners as _listeners  # noqa: E402, F401
