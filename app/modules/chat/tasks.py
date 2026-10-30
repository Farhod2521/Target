"""Chat's workers: read the prepared turn, ask Claude, publish the answer; and the sweeps."""

import uuid

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.worker import celery_app, task_session


@celery_app.task(queue="chat", ignore_result=True)
def answer_chat_turn(turn_id: str) -> None:
    from app.modules.chat.services import answer_turn, turn_payload

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        return
    with task_session() as db:
        answer_turn(db, turn_id=turn_id, payload=payload, now=utcnow())
        db.commit()


@celery_app.task(queue="chat", ignore_result=True)
def answer_refusal_turn(turn_id: str) -> None:
    """Explain one refused launch: the ready answer, or a new one kept."""
    from app.modules.chat.services import answer_refusal, turn_payload

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        return
    with task_session() as db:
        answer_refusal(db, turn_id=turn_id, payload=payload, now=utcnow())
        db.commit()


@celery_app.task(queue="chat", ignore_result=True)
def explain_change_refusal(log_id: str, language: str) -> None:
    """Explain one refused change to a running advert, and keep the answer."""
    from app.modules.chat.services.change_refusal import explain_change

    with task_session() as db:
        explain_change(db, log_id=log_id, language=language)
        db.commit()


@celery_app.task(queue="sync", ignore_result=True)
def sweep_chat_sessions() -> int:
    """Delete threads nobody has written to for thirty days."""
    from app.modules.chat.services import sweep_old_sessions

    with task_session() as db:
        gone = sweep_old_sessions(db, now=utcnow())
        db.commit()
    return gone


@celery_app.task(queue="sync", ignore_result=True)
def sweep_stuck_answers_task() -> int:
    """Close the answers whose worker never came back. Returns how many."""
    from app.modules.chat.services import sweep_stuck_answers

    with task_session() as db:
        closed = sweep_stuck_answers(db, now=utcnow())
        db.commit()
    return closed


@celery_app.task(queue="chat", ignore_result=True)
def explain_week_task(owner_id: str, pair: str = "") -> None:
    """Write the one sentence under this account's weekly report."""
    from app.modules.chat.services import explain_week

    try:
        key = uuid.UUID(str(owner_id))
    except ValueError:
        return
    with task_session() as db:
        owner = db.get(User, key)
        if owner is None:
            return
        explain_week(db, owner=owner, now=utcnow(), pair=pair)
        db.commit()


__all__ = [
    "answer_chat_turn",
    "answer_refusal_turn",
    "explain_change_refusal",
    "explain_week_task",
    "sweep_chat_sessions",
    "sweep_stuck_answers_task",
]
