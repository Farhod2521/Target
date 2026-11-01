"""A survey asked in the bot, a question a message.

The first question goes out with the morning's other news, inside the
asking hours; each answer - a press, or words typed for an open question -
rewrites the question's message with what was said and sends the next one
the conditions leave. The last answer is saved as the website saves one.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import BotClient, TextMessage

from app.common.cache import cache
from app.common.exceptions import DomainError
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.send import edit, send_to
from app.modules.notifications.services.survey_state import (
    clear,
    load,
    lock_key,
    save,
    survey_of,
)
from app.modules.notifications.services.survey_words import (
    answered_line,
    question_buttons,
    question_text,
)
from app.modules.surveys.constants import ANSWER_TEXT_MAX, QuestionKind, ResponseChannel
from app.modules.surveys.exceptions import SurveyAnswerInvalid
from app.modules.surveys.selectors.due import DueSurvey
from app.modules.surveys.services import answer_survey
from app.modules.surveys.services.sightings import note_seen

logger = logging.getLogger(__name__)
LOCK_SECONDS = 15


def start_survey(
    db: Session, *, client: BotClient, chat: TelegramChat, due: DueSurvey, now: datetime
) -> int:
    """Ask the first question, or pick up where this survey was left."""
    state = load(chat)
    if state is None or state.get("survey") != due.survey_id:
        state = {
            "survey": due.survey_id,
            "language": due.language,
            "step": 0,
            "answers": {},
            "picks": [],
        }
    state.pop("resume", None)
    note_seen(db, survey_id=due.survey_id, owner_id=chat.owner_id)
    return ask(db, client=client, chat=chat, state=state, due=due, now=now)


def resend_survey(
    db: Session, *, client: BotClient, chat: TelegramChat, token: str, now: datetime
) -> str:
    """The question «Keyinroq» put off, asked again - unless it was answered,
    put off again, or closed since."""
    state = load(chat)
    if state is None or state.get("resume") != token:
        return "stale"
    due = survey_of(db, state)
    if due is None:
        clear(chat)
        return "closed"
    state.pop("resume", None)
    sent = ask(db, client=client, chat=chat, state=state, due=due, now=now)
    return "sent" if sent else "failed"


def handle_survey_text(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    message: TextMessage,
    now: datetime,
) -> str:
    """Words typed while an open question waits; empty when none does."""
    state = load(chat)
    if state is None or "resume" in state:
        return ""
    due = survey_of(db, state)
    if due is None or due.questions[state["step"]].kind != QuestionKind.TEXT:
        return ""
    words = message.text.strip()
    if len(words) > ANSWER_TEXT_MAX:
        send_to(
            db,
            client=client,
            chat=chat,
            text=escaped(f"Javob {ANSWER_TEXT_MAX} belgidan oshmasin."),
            now=now,
        )
        return "survey_too_long"
    if not cache.add(lock_key(chat), 1, LOCK_SECONDS):
        return "survey_busy"
    try:
        return advance(
            db, client=client, chat=chat, state=state, due=due, values=[words], now=now
        )
    finally:
        cache.delete(lock_key(chat))


def advance(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    state: dict[str, Any],
    due: DueSurvey,
    values: list[str],
    now: datetime,
) -> str:
    """Write this answer down, say it under the question, and go on."""
    step = state["step"]
    question = due.questions[step]
    state["answers"][question.id] = values
    if state.get("message"):
        edit(
            client=client,
            chat_id=chat.chat_id,
            message_id=state["message"],
            text=question_text(due=due, step=step, answers=state["answers"])
            + answered_line(question=question, values=values),
        )
    ahead = [index for index in due.asked(state["answers"]) if index > step]
    state["picks"] = []
    if ahead:
        state["step"] = ahead[0]
        sent = ask(db, client=client, chat=chat, state=state, due=due, now=now)
        return "survey_next" if sent else "failed"
    return _finish(db, client=client, chat=chat, state=state, now=now)


def ask(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    state: dict[str, Any],
    due: DueSurvey,
    now: datetime,
) -> int:
    step = state["step"]
    sent = send_to(
        db,
        client=client,
        chat=chat,
        text=question_text(due=due, step=step, answers=state["answers"]),
        buttons=question_buttons(due=due, step=step, picks=state["picks"]),
        now=now,
    )
    state["message"] = sent
    save(chat, state)
    return sent


def _finish(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    state: dict[str, Any],
    now: datetime,
) -> str:
    clear(chat)
    try:
        answer_survey(
            db,
            owner=chat.owner,
            survey_id=state["survey"],
            raw=state["answers"],
            language=state["language"],
            channel=ResponseChannel.BOT,
        )
    except SurveyAnswerInvalid:
        db.rollback()
        send_to(
            db,
            client=client,
            chat=chat,
            text=escaped("Javoblarni saqlab bo'lmadi. Saytda qayta urinib ko'ring."),
            now=now,
        )
        return "survey_invalid"
    except DomainError as exc:
        db.rollback()
        send_to(db, client=client, chat=chat, text=escaped(exc.message), now=now)
        return "survey_closed"
    db.commit()
    send_to(
        db,
        client=client,
        chat=chat,
        text=escaped(
            "Rahmat! Javoblaringizni o'qiymiz va platformani shunga qarab yaxshilaymiz."
        ),
        now=now,
    )
    return "survey_answered"


__all__ = [
    "LOCK_SECONDS",
    "advance",
    "ask",
    "handle_survey_text",
    "resend_survey",
    "start_survey",
]
