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

from app.common.exceptions import NotFound
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    FEEDBACK_ANSWER_CHARS,
    FEEDBACK_CHARS,
    FEEDBACK_SKIP,
    FEEDBACK_SKIPPED,
    FEEDBACK_THANKS,
    Author,
    ButtonState,
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
                answer=(waited.text or "")[:FEEDBACK_ANSWER_CHARS],
                ticket_summary=str(ticket.get("summary", "")),
                feedback=text.strip()[:FEEDBACK_CHARS],
                language=language[:8],
                created_at=now,
                updated_at=now,
            )
        )
    waited.meta = {**meta, ANSWERED: now.isoformat()}
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
    "FeedbackMissing",
    "feedback_row",
    "is_skip",
    "mark_feedback",
    "take_feedback",
    "waiting_answer",
]
