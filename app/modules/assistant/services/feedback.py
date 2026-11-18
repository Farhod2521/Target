"""The client's word on the assistant's answers, asked before a request.

When the assistant prepares a request to Support, the answer ends with one
question - what was wrong with my answers - instead of the send button
(owner's decision, 2026-11-19). The client's next message is that answer:
it is kept for the office («Meta & AI» → AI chat) and answered here, with
no model call, by a thank-you and the send button. «Fikrim yo'q» skips the
note and still brings the button. Support's request never carries it.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import InputRefused, NotFound
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    FEEDBACK_ANSWER_CHARS,
    FEEDBACK_ASK,
    FEEDBACK_CHARS,
    FEEDBACK_SKIP,
    FEEDBACK_SKIPPED,
    FEEDBACK_THANKS,
    RATING_DOWN,
    RATING_REASONS,
    RATING_UP,
    Author,
    ButtonState,
    FeedbackKind,
    FeedbackStatus,
    MessageStatus,
    in_language,
)
from app.modules.assistant.models import (
    AssistantFeedback,
    AssistantMessage,
    AssistantSession,
)
from core.chat.markdown import render

logger = logging.getLogger(__name__)

WAITING: str = "ticket_waiting"
ANSWERED: str = "ticket_answered"
# The product's own reply to the client's word, never the model's.
REPLY: str = "feedback_reply"
RATED: str = "rating"


def waiting_answer(
    db: Session, *, session: AssistantSession | None
) -> AssistantMessage | None:
    """The thread's newest answer, when it holds a request waiting for the
    client's word. An answer further back is not waited on: the client has
    since asked something else."""
    if session is None:
        return None
    row = db.scalar(
        select(AssistantMessage)
        .where(
            AssistantMessage.session_id == session.id,
            AssistantMessage.author.in_((Author.AI, Author.STAFF)),
        )
        .order_by(AssistantMessage.created_at.desc())
        .limit(1)
    )
    if row is None or row.author != Author.AI or row.status != MessageStatus.DONE:
        return None
    meta = row.meta or {}
    if not isinstance(meta.get(WAITING), dict) or meta.get(ANSWERED):
        return None
    return row


def is_skip(text: str) -> bool:
    said = " ".join(text.split()).casefold()
    return any(said == words.casefold() for words in FEEDBACK_SKIP.values())


def take_feedback(
    db: Session,
    *,
    owner: User,
    waited: AssistantMessage,
    answer: AssistantMessage,
    text: str,
    language: str,
    now: datetime,
) -> tuple[str, list[dict[str, Any]], str]:
    """Keep the client's word, close the wait, and fill the answer's row with
    the thank-you and the send button. Returns ``(text, buttons, html)``."""
    meta = dict(waited.meta or {})
    ticket = dict(meta[WAITING])
    skipped = is_skip(text)
    if not skipped:
        db.add(
            AssistantFeedback(
                owner_id=owner.id,
                session_id=waited.session_id,
                message_id=waited.id,
                question=str(ticket.get("question", ""))[:FEEDBACK_CHARS],
                answer=_without_ask(waited.text or "")[:FEEDBACK_ANSWER_CHARS],
                ticket_summary=str(ticket.get("summary", "")),
                kind=FeedbackKind.TICKET,
                feedback=text.strip()[:FEEDBACK_CHARS],
                language=language[:8],
                created_at=now,
                updated_at=now,
            )
        )
    waited.meta = {**meta, ANSWERED: now.isoformat()}
    # The thank-you is the product's own words: nothing to rate there.
    answer.meta = {**(answer.meta or {}), REPLY: True}
    words = in_language(FEEDBACK_SKIPPED if skipped else FEEDBACK_THANKS, language)
    buttons = [{**ticket, "state": ButtonState.OPEN}]
    html = render(words)
    answer.text = words
    answer.html = html
    answer.status = MessageStatus.DONE
    answer.buttons = buttons
    answer.replies = []
    answer.updated_at = now
    db.flush()
    logger.info(
        "assistant_feedback",
        extra={"owner_id": str(owner.id), "skipped": skipped},
    )
    return words, buttons, html


def _without_ask(text: str) -> str:
    """The answer as the assistant wrote it, without the question the
    product put after it."""
    for words in FEEDBACK_ASK.values():
        if text.endswith(words):
            return text[: -len(words)].rstrip()
    return text


class AnswerMissing(NotFound):
    def __init__(self) -> None:
        super().__init__("Javob topilmadi.")


class RatingRefused(InputRefused):
    def __init__(self, field: str, words: str) -> None:
        super().__init__({field: words})


def rate_answer(
    db: Session,
    *,
    owner: User,
    message_id: uuid.UUID,
    value: str,
    reason: str,
    note: str,
    language: str,
    now: datetime,
) -> AssistantMessage:
    """👍 or 👎 under one of the assistant's answers. One rating an answer:
    pressed again, it is changed. A 👎 waits for the office; a 👍 is counted
    and needs nobody to read it."""
    from app.modules.assistant.selectors.threads import message_for

    if value not in (RATING_UP, RATING_DOWN):
        raise RatingRefused("value", "Baho: up yoki down.")
    if reason and (value != RATING_DOWN or reason not in RATING_REASONS):
        raise RatingRefused("reason", "Sabab ro'yxatdagilardan biri bo'lsin.")
    row = message_for(db, owner=owner, pk=message_id, lock=True)
    if (
        row is None
        or row.author != Author.AI
        or row.status != MessageStatus.DONE
        or not (row.text or "").strip()
        or (row.meta or {}).get(REPLY)
    ):
        raise AnswerMissing
    words = " ".join(note.split())[:FEEDBACK_CHARS] if value == RATING_DOWN else ""
    found = db.scalar(
        select(AssistantFeedback).where(
            AssistantFeedback.message_id == row.id,
            AssistantFeedback.kind == FeedbackKind.RATING,
        )
    )
    if found is None:
        found = AssistantFeedback(
            owner_id=owner.id,
            session_id=row.session_id,
            message_id=row.id,
            kind=FeedbackKind.RATING,
            question=_asked_before(db, row=row)[:FEEDBACK_CHARS],
            answer=_without_ask(row.text or "")[:FEEDBACK_ANSWER_CHARS],
            created_at=now,
        )
        db.add(found)
    found.rating = value
    found.reason = reason if value == RATING_DOWN else ""
    found.feedback = words
    found.language = language[:8]
    # A 👍 is counted, not read; a 👎 - also one turned from a 👍 - is read.
    done = value == RATING_UP
    found.status = FeedbackStatus.DONE if done else FeedbackStatus.OPEN
    found.closed_at = now if done else None
    found.updated_at = now
    row.meta = {**(row.meta or {}), RATED: value}
    db.flush()
    logger.info(
        "assistant_rating",
        extra={"owner_id": str(owner.id), "value": value, "reason": reason},
    )
    return row


def _asked_before(db: Session, *, row: AssistantMessage) -> str:
    """The client's words this answer was written for."""
    asked = db.scalar(
        select(AssistantMessage.text)
        .where(
            AssistantMessage.session_id == row.session_id,
            AssistantMessage.author == Author.USER,
            AssistantMessage.created_at <= row.created_at,
        )
        .order_by(AssistantMessage.created_at.desc())
        .limit(1)
    )
    return str(asked or "")


class FeedbackMissing(NotFound):
    def __init__(self) -> None:
        super().__init__("Fikr topilmadi.")


def feedback_row(db: Session, pk: uuid.UUID) -> AssistantFeedback:
    found = db.get(AssistantFeedback, pk)
    if found is None:
        raise FeedbackMissing
    return found


def mark_feedback(
    db: Session, *, row: AssistantFeedback, done: bool, now: datetime
) -> AssistantFeedback:
    """Read by the office, or put back to be read."""
    row.status = FeedbackStatus.DONE if done else FeedbackStatus.OPEN
    row.closed_at = now if done else None
    row.updated_at = now
    db.flush()
    return row


__all__ = [
    "AnswerMissing",
    "FeedbackMissing",
    "RatingRefused",
    "feedback_row",
    "is_skip",
    "mark_feedback",
    "rate_answer",
    "take_feedback",
    "waiting_answer",
]
