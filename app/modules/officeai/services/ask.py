"""A question in: the rows on the thread, and the turn a worker answers."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.dates import localtime
from app.common.exceptions import DomainError
from app.common.llm import prompts
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMCallStatus, LLMPurpose
from app.modules.audit.models import LLMCall
from app.modules.backoffice.constants import ROLE_LABELS, Role
from app.modules.backoffice.permissions import roles_of
from app.modules.officeai.constants import (
    ANSWER_MAX_TOKENS,
    MAX_QUESTION_CHARS,
    PROMPT_NAME,
    QUESTIONS_PER_DAY,
    TITLE_CHARS,
    TURN_KEY,
    TURN_TTL_SECONDS,
    Author,
    MessageStatus,
)
from app.modules.officeai.models import OfficeAiMessage, OfficeAiThread
from app.modules.officeai.selectors.threads import history
from core.chat.numbers import figures_in


class EmptyQuestion(DomainError):
    status_code = 400
    code = "office_ai_empty"

    def __init__(self) -> None:
        super().__init__("Savol bo'sh.")


class QuestionsSpent(DomainError):
    status_code = 429
    code = "office_ai_spent"

    def __init__(self) -> None:
        super().__init__(
            f"Bugungi {QUESTIONS_PER_DAY} ta savol tugadi. Ertaga yana so'rash mumkin."
        )


@dataclass(frozen=True, slots=True)
class Turn:
    turn_id: str
    thread_id: str
    message_id: str
    left: int


def questions_today(db: Session, *, staff: User, now: datetime) -> int:
    """Answers this person had today, office time."""
    since = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count(LLMCall.id)).where(
                LLMCall.owner_id == staff.id,
                LLMCall.purpose == LLMPurpose.OFFICE,
                LLMCall.status == LLMCallStatus.OK,
                LLMCall.created_at >= since,
            )
        )
        or 0
    )


def questions_left(db: Session, *, staff: User, now: datetime) -> int:
    return max(QUESTIONS_PER_DAY - questions_today(db, staff=staff, now=now), 0)


def _asker(db: Session, *, staff: User, sees_money: bool, now: datetime) -> str:
    """Who asks and when: the part of the prompt that changes, uncached."""
    # A superuser holds every role by name; saying so is shorter.
    held = frozenset() if staff.is_superuser else roles_of(db, staff)
    roles = ", ".join(str(ROLE_LABELS[role]) for role in Role if str(role) in held) or (
        "superuser" if staff.is_superuser else "staff"
    )
    local = localtime(now)
    return "\n".join(
        [
            "## Context",
            f"- Today: {local:%Y-%m-%d} ({local:%A}), office time {local:%H:%M}.",
            f"- Asking: {staff.full_name or staff.email} ({roles}).",
            "- Sees money: "
            + ("yes" if sees_money else "no - money look-ups are not available"),
        ]
    )


def start_turn(
    db: Session,
    *,
    staff: User,
    question: str,
    thread: OfficeAiThread | None,
    sees_money: bool,
    now: datetime,
) -> Turn:
    """Write the question and an empty answer, and leave the turn for a
    worker. Nothing is sent to the model here."""
    from llmkit import render

    text = " ".join(question.split())[:MAX_QUESTION_CHARS]
    if not text:
        raise EmptyQuestion
    left = questions_left(db, staff=staff, now=now)
    if left <= 0:
        raise QuestionsSpent
    if thread is None:
        thread = OfficeAiThread(staff_id=staff.id, title=text[:TITLE_CHARS])
        db.add(thread)
        db.flush()
    said = history(db, thread=thread)
    db.add(
        OfficeAiMessage(
            staff_id=staff.id,
            thread_id=thread.id,
            author=Author.USER,
            text=text,
            status=MessageStatus.DONE,
            created_at=now,
        )
    )
    answer = OfficeAiMessage(
        staff_id=staff.id,
        thread_id=thread.id,
        author=Author.AI,
        status=MessageStatus.PENDING,
        # A moment after the question, so the two never sort the wrong way.
        created_at=now.replace(microsecond=min(now.microsecond + 1, 999_999)),
    )
    db.add(answer)
    thread.last_message_at = now
    db.flush()
    template, version = prompts().get(PROMPT_NAME)
    turn_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "question": text,
        "system": render(template, {}),
        "system_tail": _asker(db, staff=staff, sees_money=sees_money, now=now),
        "history": said,
        "quoted": sorted(figures_in(" ".join([text, *(w for _r, w in said)]))),
        "staff_id": str(staff.id),
        "sees_money": sees_money,
        "message_id": str(answer.id),
        "thread_id": str(thread.id),
        "prompt_version": version,
        "max_tokens": ANSWER_MAX_TOKENS,
    }
    cache.set(TURN_KEY.format(turn_id=turn_id), payload, TURN_TTL_SECONDS)
    return Turn(
        turn_id=turn_id,
        thread_id=str(thread.id),
        message_id=str(answer.id),
        left=left - 1,
    )


def turn_payload(*, turn_id: str) -> dict[str, Any] | None:
    value = cache.get(TURN_KEY.format(turn_id=turn_id))
    return value if isinstance(value, dict) else None


__all__ = [
    "EmptyQuestion",
    "QuestionsSpent",
    "Turn",
    "questions_left",
    "questions_today",
    "start_turn",
    "turn_payload",
]
