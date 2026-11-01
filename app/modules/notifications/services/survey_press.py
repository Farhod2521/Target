"""A press under a survey question: an option, a tick, «Tayyor», a number,
«O'tkazib yuborish» or «Keyinroq».

Only the press on the question the chat is on counts; one on an older
question is answered "stale" and its buttons are taken away.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, object_session
from telegramkit import BotClient, ButtonPress

from app.common.cache import cache
from app.common.i18n import override
from app.modules.notifications.keys import read_survey_press
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.send import answer, edit, edit_buttons
from app.modules.notifications.services.survey_bot import LOCK_SECONDS, advance
from app.modules.notifications.services.survey_state import (
    clear,
    load,
    lock_key,
    save,
    survey_of,
)
from app.modules.notifications.services.survey_words import (
    question_buttons,
    question_text,
)
from app.modules.surveys.constants import SNOOZE_SECONDS, QuestionKind
from app.modules.surveys.selectors.due import DueSurvey
from app.modules.surveys.services import note_later, snooze_survey


def is_survey_press(data: str) -> bool:
    return read_survey_press(data) is not None


def handle_survey_press(
    db: Session, *, client: BotClient, press: ButtonPress, now: datetime
) -> str:
    chat = chat_by_id(db, chat_id=press.chat_id)
    if chat is None or not chat.is_active:
        answer(client=client, query_id=press.query_id, text="Telegram ulanmagan.")
        return "unlinked"
    with override(chat.owner.language):
        if press.sender.id != chat.chat_id:
            answer(
                client=client,
                query_id=press.query_id,
                text="Bu tugma sizga tegishli emas.",
                alert=True,
            )
            return "stranger"
        return _taken(db, client=client, chat=chat, press=press, now=now)


def _taken(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    press: ButtonPress,
    now: datetime,
) -> str:
    parsed = read_survey_press(press.data)
    state = load(chat)
    if parsed is None or state is None or parsed[0] != state["step"]:
        answer(client=client, query_id=press.query_id, text="Bu savol eskirgan.")
        edit_buttons(client=client, chat_id=chat.chat_id, message_id=press.message_id)
        return "stale"
    if not cache.add(lock_key(chat), 1, LOCK_SECONDS):
        answer(client=client, query_id=press.query_id)
        return "busy"
    try:
        return _pressed(
            db,
            client=client,
            chat=chat,
            press=press,
            state=state,
            parsed=parsed,
            now=now,
        )
    finally:
        cache.delete(lock_key(chat))


def _pressed(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    press: ButtonPress,
    state: dict[str, Any],
    parsed: tuple[int, str, int],
    now: datetime,
) -> str:
    due = survey_of(db, state)
    if due is None:
        clear(chat)
        answer(
            client=client, query_id=press.query_id, text="Bu so'rovnoma endi yopilgan."
        )
        edit_buttons(client=client, chat_id=chat.chat_id, message_id=press.message_id)
        return "closed"
    step, action, value = parsed
    question = due.questions[step]
    if action == "l":
        return _later(client=client, chat=chat, press=press, state=state, due=due)
    if action == "t":
        picks = set(state["picks"]) ^ {value}
        state["picks"] = sorted(pick for pick in picks if pick < len(question.options))
        save(chat, state)
        answer(client=client, query_id=press.query_id)
        edit(
            client=client,
            chat_id=chat.chat_id,
            message_id=press.message_id,
            text=question_text(due=due, step=step, answers=state["answers"]),
            buttons=question_buttons(due=due, step=step, picks=state["picks"]),
        )
        return "survey_ticked"
    values = _values(
        question=question, action=action, value=value, picks=state["picks"]
    )
    if values is None:
        answer(client=client, query_id=press.query_id, text="Javob bering.", alert=True)
        return "survey_refused"
    answer(client=client, query_id=press.query_id)
    return advance(
        db, client=client, chat=chat, state=state, due=due, values=values, now=now
    )


def _values(
    *, question: Any, action: str, value: int, picks: list[int]
) -> list[str] | None:
    """The answer a press gives, or None when it gives none it may."""
    if action == "s":
        return None if question.is_required else []
    if (
        action == "o"
        and question.kind == QuestionKind.CHOICE
        and value < len(question.options)
    ):
        return [str(value)]
    if action == "d" and question.kind == QuestionKind.CHOICE:
        if question.is_required and not picks:
            return None
        return [str(pick) for pick in picks]
    if (
        action == "n"
        and question.kind == QuestionKind.NUMBER
        and value in question.numbers
    ):
        return [str(value)]
    return None


def _later(
    *,
    client: BotClient,
    chat: TelegramChat,
    press: ButtonPress,
    state: dict[str, Any],
    due: DueSurvey,
) -> str:
    """«Keyinroq»: put the survey off everywhere, and ask this question again
    once the wait is up - unless something else asked it first."""
    from app.modules.notifications.tasks import resend_survey_task

    note_later(object_session(chat), survey_id=due.survey_id, owner_id=chat.owner_id)
    snooze_survey(user=chat.owner)
    token = uuid.uuid4().hex
    state["resume"] = token
    state.pop("message", None)
    save(chat, state)
    answer(client=client, query_id=press.query_id)
    edit(
        client=client,
        chat_id=chat.chat_id,
        message_id=press.message_id,
        text=question_text(due=due, step=state["step"], answers=state["answers"])
        + "\n\n"
        + "Yaxshi, 10 daqiqadan keyin shu savoldan davom etamiz.",
    )
    resend_survey_task.apply_async(
        (str(chat.owner_id), token), countdown=SNOOZE_SECONDS + 5
    )
    return "survey_later"


__all__ = ["handle_survey_press", "is_survey_press"]
