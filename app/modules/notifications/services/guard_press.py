"""A button pressed under one of the guard's findings.

The same answers the cabinet gives - see
:func:`app.modules.agent.services.answer_guard.answer_guard`. Only the
chat's own owner answers, and only a finding of theirs; one that is closed
or already answered with a change is said to be gone. The pressed message is
rewritten at once with what became of the press - see
:func:`app.modules.notifications.services.announce_guard.show_state`.
"""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import BotClient, ButtonPress

from app.common.exceptions import DomainError
from app.common.i18n import override
from app.modules.agent.guard_follow_copy import follow_text
from app.modules.agent.services.answer_guard import Answered, answer_guard
from app.modules.notifications.constants import GUARD_CALLBACKS
from app.modules.notifications.keys import read_press
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.announce_guard import show_state
from app.modules.notifications.services.send import answer

_ANSWER_OF = {code: name for name, code in GUARD_CALLBACKS.items()}


def is_guard_press(data: str) -> bool:
    found = read_press(data)
    return found is not None and found[0] in _ANSWER_OF


def handle_guard_press(
    db: Session, *, client: BotClient, press: ButtonPress, now: datetime
) -> str:
    from app.modules.agent.routers import guard_said

    chat = chat_by_id(db, chat_id=press.chat_id)
    if chat is None or not chat.is_active:
        answer(client=client, query_id=press.query_id, text="Telegram ulanmagan.")
        return "unlinked"
    found = read_press(press.data)
    with override(chat.owner.language):
        if press.sender.id != chat.chat_id or found is None:
            answer(
                client=client,
                query_id=press.query_id,
                text="Bu tugma sizga tegishli emas.",
                alert=True,
            )
            return "stranger"
        code, alert_id = found
        chosen = _ANSWER_OF[code]
        try:
            done = answer_guard(
                db, user=chat.owner, alert_id=alert_id, answer=chosen, now=now
            )
        except DomainError as refused:
            db.rollback()
            answer(
                client=client,
                query_id=press.query_id,
                text=str(refused) or "Bu xabar endi dolzarb emas.",
                alert=True,
            )
            return "refused"
        db.commit()
        answer(client=client, query_id=press.query_id, text=_said(done, guard_said))
        show_state(db, client=client, row=done.row, message_id=press.message_id)
        return f"guard_{done.answer}:{done.state}"


def _said(done: Answered, guard_said: Callable[[str], str]) -> str:
    if done.state == "checking":
        return follow_text("said.checking")
    if done.state == "cancelled":
        return follow_text("said.cancel")
    return guard_said(done.answer)


__all__ = ["handle_guard_press", "is_guard_press"]
