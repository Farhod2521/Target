"""«Reklamani to'xtatish» and «Kuzataman» pressed under a morning price rise (TZ 1.5).

The same answers the cabinet gives: the group is paused only on this press,
and «Kuzataman» keeps the group quiet for 72 hours. Only the chat's own
owner answers, and only a rise of theirs; one already closed is said to be gone.
"""

from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import BotClient, ButtonPress

from app.common.exceptions import DomainError
from app.common.i18n import override
from app.modules.agent.services.answer_price import answer_pause, answer_watching
from app.modules.notifications.constants import (
    CALLBACK_PRICE_PAUSE,
    CALLBACK_PRICE_WATCH,
)
from app.modules.notifications.keys import read_press
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.send import answer

PRICE_PRESSES = frozenset({CALLBACK_PRICE_PAUSE, CALLBACK_PRICE_WATCH})


def is_price_press(data: str) -> bool:
    found = read_press(data)
    return found is not None and found[0] in PRICE_PRESSES


def handle_price_press(
    db: Session, *, client: BotClient, press: ButtonPress, now: datetime
) -> str:
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
        action, alert_id = found
        pausing = action == CALLBACK_PRICE_PAUSE
        try:
            if pausing:
                answer_pause(db, user=chat.owner, alert_id=alert_id, now=now)
            else:
                answer_watching(db, user=chat.owner, alert_id=alert_id, now=now)
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
        answer(
            client=client,
            query_id=press.query_id,
            text="To'xtatish so'rovi yuborildi."
            if pausing
            else "Javobingiz saqlandi. 72 soat kuzatamiz.",
        )
        return "price_paused" if pausing else "price_watching"


__all__ = ["handle_price_press", "is_price_press"]
