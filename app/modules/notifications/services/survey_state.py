"""Where one chat's survey stands, between the presses that answer it.

Kept in the cache, under the chat, for three days: the survey id and its
language, the question it is on, the answers so far, the ticks on a
many-answer question, and the message the current question is in. JSON all
the way down, so the cache can hold it.
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.businesses.selectors import business_timezone
from app.modules.notifications.constants import (
    SURVEY_STATE_KEY,
    SURVEY_STATE_TTL_SECONDS,
)
from app.modules.notifications.models import TelegramChat
from app.modules.surveys.selectors.due import DueSurvey, survey_for


def survey_of(db: Session, state: dict[str, Any]) -> DueSurvey | None:
    """The survey this state is about, or None once it was closed. A survey
    edited since may have fewer questions: the chat goes on from the first
    one still unanswered."""
    due = survey_for(db, survey_id=state["survey"], language=state["language"])
    if due is not None and not 0 <= state.get("step", 0) < len(due.questions):
        state["step"] = first_open(due, state.get("answers") or {})
        state["picks"] = []
    return due


def first_open(due: DueSurvey, answers: dict[str, Any]) -> int:
    """The first question asked that has no answer yet; the last one if all do."""
    asked = due.asked(answers)
    for index in asked:
        if due.questions[index].id not in answers:
            return index
    return asked[-1] if asked else 0


def local_now(db: Session, *, owner: User, now: datetime) -> datetime:
    """The owner's own clock: the business's timezone, or the deployment's."""
    name = business_timezone(db, owner=owner)
    try:
        zone = ZoneInfo(name or settings.default_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(settings.default_timezone)
    return now.astimezone(zone)


def local_today(db: Session, *, owner: User, now: datetime) -> date:
    return local_now(db, owner=owner, now=now).date()


def load(chat: TelegramChat) -> dict[str, Any] | None:
    state = cache.get(SURVEY_STATE_KEY.format(chat_id=chat.chat_id))
    return state if isinstance(state, dict) else None


def save(chat: TelegramChat, state: dict[str, Any]) -> None:
    cache.set(
        SURVEY_STATE_KEY.format(chat_id=chat.chat_id), state, SURVEY_STATE_TTL_SECONDS
    )


def clear(chat: TelegramChat) -> None:
    cache.delete(SURVEY_STATE_KEY.format(chat_id=chat.chat_id))


def lock_key(chat: TelegramChat) -> str:
    """Two presses at once on one question would both advance it."""
    return SURVEY_STATE_KEY.format(chat_id=chat.chat_id) + ":lock"


__all__ = [
    "clear",
    "first_open",
    "load",
    "local_now",
    "local_today",
    "lock_key",
    "save",
    "survey_of",
]
