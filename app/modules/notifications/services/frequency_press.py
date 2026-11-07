"""«Reklama yaxshi ishlayapti» pressed under a morning frequency message (TZ 6.3).

The same answer the cabinet gives: kept, and the next message comes only at
the next level - at 3.00 after a day. Only the chat's own owner answers, and
only an alert of theirs; one already closed is said to be gone.
"""

from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import BotClient, ButtonPress

from app.common.i18n import override
from app.modules.agent.exceptions import FrequencyAlertGone
from app.modules.agent.services.answer_frequency import answer_working_well
from app.modules.notifications.constants import CALLBACK_FREQUENCY_FINE
from app.modules.notifications.keys import read_press
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.services.send import answer


def is_frequency_press(data: str) -> bool:
    found = read_press(data)
    return found is not None and found[0] == CALLBACK_FREQUENCY_FINE


def handle_frequency_press(
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
        try:
            answer_working_well(db, user=chat.owner, alert_id=found[1], now=now)
        except FrequencyAlertGone:
            db.rollback()
            answer(
                client=client,
                query_id=press.query_id,
                text="Bu xabar endi dolzarb emas.",
            )
            return "gone"
        db.commit()
        answer(client=client, query_id=press.query_id, text="Javobingiz saqlandi.")
        return "frequency_fine"


__all__ = ["handle_frequency_press", "is_frequency_press"]
