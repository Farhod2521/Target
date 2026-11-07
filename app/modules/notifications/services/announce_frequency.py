"""The morning's frequency levels: the groups the same people see too often.

Sent right after the agent writes the levels, once a day, every level of the
day in one message (TZ 6.5.2) - as many as Telegram's length allows; the rest
go the next morning. Each level carries its two answers (TZ 6.3): «Qo'shimcha
kreativ qo'shamiz» opens the site's copy window for the group, «Reklama
yaxshi ishlayapti» is answered right here.
"""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session
from telegramkit import Button

from app.common import timezone
from app.common.config import settings
from app.common.i18n import override
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent.frequency_copy import (
    ADD_CREATIVE,
    WORKING_WELL,
    frequency_body,
    frequency_title,
)
from app.modules.agent.models import FrequencyAlert
from app.modules.agent.selectors.frequency import alerts_to_show
from app.modules.billing.selectors import has_live_subscription
from app.modules.chat.selectors import cabinet_clock
from app.modules.miniapp.services import door_url
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import (
    CALLBACK_FREQUENCY_FINE,
    FREQUENCY_MAX_CHARS,
    NoticeKind,
)
from app.modules.notifications.keys import press_data
from app.modules.notifications.selectors import chat_for, left_keys
from app.modules.notifications.selectors.inbox_frequency import frequency_key
from app.modules.notifications.services.compose import _bold, escaped
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.send import send_to
from core.inbox import left_key


def deliver_frequency_for(db: Session, *, owner: User, now: datetime) -> bool:
    """The levels not yet told, in one message for the owner's day."""
    if not has_live_subscription(db, owner=owner):
        return False
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_suggestions or not is_configured():
        return False
    left = left_keys(db, owner=owner, now=now)
    rows = _fitting(
        [
            row
            for row in unsent(db, owner=owner, now=now)
            if left_key(frequency_key(row)) not in left
        ]
    )
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
            buttons=frequency_buttons(rows),
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


def _fitting(rows: list[FrequencyAlert]) -> list[FrequencyAlert]:
    """As many levels as one message holds, highest first."""
    kept: list[FrequencyAlert] = []
    for row in rows:
        if kept and len(frequency_message([*kept, row])) > FREQUENCY_MAX_CHARS:
            break
        kept.append(row)
    return kept


def frequency_message(rows: list[FrequencyAlert]) -> str:
    many = len(rows) > 1
    lines: list[str] = []
    for number, row in enumerate(rows, start=1):
        title = f"{number}. {frequency_title(row)}" if many else frequency_title(row)
        lines += [_bold(title), escaped(frequency_body(row)), ""]
    return "\n".join(lines).strip()


def frequency_buttons(rows: list[FrequencyAlert]) -> tuple[Button, ...]:
    """Two per level, numbered as the message numbers them when there are several."""
    many = len(rows) > 1
    found: list[Button] = []
    for number, row in enumerate(rows, start=1):
        mark = f"{number}. " if many else ""
        if settings.site_url.startswith("https://"):
            found.append(
                Button(
                    text=f"{mark}{ADD_CREATIVE}",
                    web_app=door_url(
                        destination=reverse("agent:frequency_creative", args=[row.id])
                    ),
                )
            )
        found.append(
            Button(
                text=f"{mark}{WORKING_WELL}",
                data=press_data(action=CALLBACK_FREQUENCY_FINE, pk=row.id),
            )
        )
    return tuple(found)


__all__ = [
    "deliver_frequency_for",
    "frequency_buttons",
    "frequency_message",
    "unsent",
]
