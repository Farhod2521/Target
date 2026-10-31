"""The morning's frequency levels: the groups the same people see too often.

Sent right after the agent writes the levels, once a day, a few levels a
message. Said short with the way to the center: the answers - «it works
well», «add a creative» - are given there until the ads action layer is done.
"""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.common import timezone
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.agent.frequency_copy import frequency_body, frequency_title
from app.modules.agent.models import FrequencyAlert
from app.modules.agent.selectors.frequency import alerts_to_show
from app.modules.billing.selectors import has_live_subscription
from app.modules.chat.selectors import cabinet_clock
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import FREQUENCY_MAX_ITEMS, NoticeKind
from app.modules.notifications.selectors import chat_for
from app.modules.notifications.services.compose import _bold, center_button, escaped
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.send import send_to


def deliver_frequency_for(db: Session, *, owner: User, now: datetime) -> bool:
    """The levels not yet told, in one message for the owner's day."""
    if not has_live_subscription(db, owner=owner):
        return False
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_suggestions or not is_configured():
        return False
    rows = unsent(db, owner=owner, now=now)[:FREQUENCY_MAX_ITEMS]
    clock = cabinet_clock(db, owner=owner)
    if not rows or clock is None:
        return False
    day = timezone.localtime(now, clock.tzinfo()).date().isoformat()
    notice = claim(db, chat=chat, kind=NoticeKind.FREQUENCY, subject=day)
    if notice is None:
        return False
    with override(owner.language), bot() as client:
        message_id = send_to(
            db,
            client=client,
            chat=chat,
            text=frequency_message(rows),
            buttons=center_button(),
            now=now,
        )
    stamp(db, notice=notice, message_id=message_id, now=now)
    if message_id:
        db.execute(
            update(FrequencyAlert)
            .where(
                FrequencyAlert.owner_id == owner.id,
                FrequencyAlert.id.in_([row.id for row in rows]),
            )
            .values(telegram_sent_at=now, telegram_message_id=message_id)
            .execution_options(synchronize_session=False)
        )
    db.commit()
    return bool(message_id)


def unsent(db: Session, *, owner: User, now: datetime) -> list[FrequencyAlert]:
    """Open levels never told, or hidden and come back since they were."""
    return [
        row
        for row in alerts_to_show(db, owner=owner, now=now)
        if row.telegram_sent_at is None
        or (row.hidden_until is not None and row.telegram_sent_at < row.hidden_until)
    ]


def frequency_message(rows: list[FrequencyAlert]) -> str:
    lines: list[str] = []
    for number, row in enumerate(rows, start=1):
        lines += [
            _bold(f"{number}. {frequency_title(row)}"),
            escaped(frequency_body(row)),
            "",
        ]
    lines.append(escaped("Javob berish uchun «Batafsil» ni bosing."))
    return "\n".join(lines)


__all__ = ["deliver_frequency_for", "frequency_message", "unsent"]
