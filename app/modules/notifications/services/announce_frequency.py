"""The morning's message: price rises and frequency levels, once a day.

Sent right after the agent writes them, everything of the day in one message
(TZ 1.6.3, 6.5.2) - as many as Telegram's length allows; the rest go the next
morning. The price rises come first, each with its three answers (TZ 1.5);
a frequency level of the same group and night is said inside its price rise
(TZ 6.5.6). A level on its own carries its two answers (TZ 6.3). «... kreativ
...» opens the site's copy window for the group; the rest are answered here.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session
from telegramkit import Button

from app.common import timezone
from app.common.config import settings
from app.common.i18n import override
from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent import price_copy
from app.modules.agent.frequency_copy import (
    ADD_CREATIVE,
    WORKING_WELL,
    frequency_body,
    frequency_title,
)
from app.modules.agent.models import FrequencyAlert, PriceAlert
from app.modules.agent.selectors.frequency import alerts_to_show
from app.modules.agent.selectors.price_alerts import (
    merged_frequencies,
    price_alerts_to_show,
)
from app.modules.billing.selectors import has_live_subscription
from app.modules.chat.selectors import cabinet_clock
from app.modules.miniapp.services import door_url
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import (
    CALLBACK_FREQUENCY_FINE,
    CALLBACK_PRICE_PAUSE,
    CALLBACK_PRICE_WATCH,
    FREQUENCY_MAX_CHARS,
    NoticeKind,
)
from app.modules.notifications.keys import press_data
from app.modules.notifications.selectors import chat_for, left_keys
from app.modules.notifications.selectors.inbox_frequency import frequency_key
from app.modules.notifications.selectors.inbox_price import price_key
from app.modules.notifications.services.compose import _bold, escaped
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.send import send_to
from core.inbox import left_key


def deliver_frequency_for(db: Session, *, owner: User, now: datetime) -> bool:
    """The price rises and levels not yet told, in one message for the owner's day."""
    if not has_live_subscription(db, owner=owner):
        return False
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_suggestions or not is_configured():
        return False
    left = left_keys(db, owner=owner, now=now)
    entries = _fitting(
        [
            entry
            for entry in morning_entries(db, owner=owner, now=now)
            if entry.key not in left
        ]
    )
    clock = cabinet_clock(db, owner=owner)
    if not entries or clock is None:
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
            text=morning_message(entries),
            buttons=morning_buttons(entries),
            now=now,
        )
    stamp(db, notice=notice, message_id=message_id, now=now)
    if message_id:
        _stamped(db, owner=owner, entries=entries, now=now, message_id=message_id)
    db.commit()
    return bool(message_id)


@dataclass(frozen=True, slots=True)
class Entry:
    """One numbered part of the morning's message: a price rise, with the
    frequency level said inside it, or a frequency level alone."""

    price: PriceAlert | None = None
    frequency: FrequencyAlert | None = None

    @property
    def key(self) -> str:
        if self.price is not None:
            return left_key(price_key(self.price))
        assert self.frequency is not None
        return left_key(frequency_key(self.frequency))

    @property
    def title(self) -> str:
        if self.price is not None:
            return price_copy.price_title(self.price)
        assert self.frequency is not None
        return frequency_title(self.frequency)

    @property
    def body(self) -> str:
        if self.price is not None:
            return price_copy.price_body(self.price, frequency=self.frequency)
        assert self.frequency is not None
        return frequency_body(self.frequency)


def morning_entries(db: Session, *, owner: User, now: datetime) -> list[Entry]:
    """The price rises not yet told, dearest first, then the levels."""
    prices = [
        row
        for row in price_alerts_to_show(db, owner=owner)
        if row.telegram_sent_at is None
    ]
    merged = merged_frequencies(db, rows=prices)
    inside = {level.id for level in merged.values()}
    return [
        *(
            Entry(price=row, frequency=merged.get(row.adset_external_id))
            for row in prices
        ),
        *(
            Entry(frequency=row)
            for row in unsent(db, owner=owner, now=now)
            if row.id not in inside
        ),
    ]


def _stamped(
    db: Session, *, owner: User, entries: list[Entry], now: datetime, message_id: int
) -> None:
    prices = [entry.price.id for entry in entries if entry.price is not None]
    levels = [entry.frequency.id for entry in entries if entry.frequency is not None]
    values = {"telegram_sent_at": now, "telegram_message_id": message_id}
    for model, ids in ((PriceAlert, prices), (FrequencyAlert, levels)):
        if ids:
            db.execute(
                update(model)
                .where(model.owner_id == owner.id, model.id.in_(ids))
                .values(**values)
                .execution_options(synchronize_session=False)
            )


def unsent(db: Session, *, owner: User, now: datetime) -> list[FrequencyAlert]:
    """Open levels never told, or hidden and come back since they were."""
    return [
        row
        for row in alerts_to_show(db, owner=owner, now=now)
        if row.telegram_sent_at is None
        or (row.hidden_until is not None and row.telegram_sent_at < row.hidden_until)
    ]


def _fitting(entries: list[Entry]) -> list[Entry]:
    """As many parts as one message holds, in their order."""
    kept: list[Entry] = []
    for entry in entries:
        if kept and len(morning_message([*kept, entry])) > FREQUENCY_MAX_CHARS:
            break
        kept.append(entry)
    return kept


def morning_message(entries: list[Entry]) -> str:
    many = len(entries) > 1
    lines: list[str] = []
    for number, entry in enumerate(entries, start=1):
        title = f"{number}. {entry.title}" if many else entry.title
        lines += [_bold(title), escaped(entry.body), ""]
    return "\n".join(lines).strip()


def morning_buttons(entries: list[Entry]) -> tuple[Button, ...]:
    """Each part's answers, numbered as the message numbers them when there are several."""
    many = len(entries) > 1
    found: list[Button] = []
    for number, entry in enumerate(entries, start=1):
        mark = f"{number}. " if many else ""
        if entry.price is not None:
            found += _price_buttons(entry.price, mark)
        elif entry.frequency is not None:
            found += _frequency_buttons(entry.frequency, mark)
    return tuple(found)


def _price_buttons(row: PriceAlert, mark: str) -> list[Button]:
    found: list[Button] = []
    if settings.site_url.startswith("https://"):
        found.append(
            Button(
                text=f"{mark}{price_copy.ADD_CREATIVE}",
                web_app=door_url(
                    destination=reverse("agent:price_creative", args=[row.id])
                ),
            )
        )
    found += [
        Button(
            text=f"{mark}{price_copy.PAUSE}",
            data=press_data(action=CALLBACK_PRICE_PAUSE, pk=row.id),
        ),
        Button(
            text=f"{mark}{price_copy.WATCHING}",
            data=press_data(action=CALLBACK_PRICE_WATCH, pk=row.id),
        ),
    ]
    return found


def _frequency_buttons(row: FrequencyAlert, mark: str) -> list[Button]:
    found: list[Button] = []
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
    return found


def frequency_message(rows: list[FrequencyAlert]) -> str:
    """Levels alone, as the morning says them."""
    return morning_message([Entry(frequency=row) for row in rows])


def frequency_buttons(rows: list[FrequencyAlert]) -> tuple[Button, ...]:
    """Two per level, numbered as the message numbers them when there are several."""
    return morning_buttons([Entry(frequency=row) for row in rows])


__all__ = [
    "Entry",
    "deliver_frequency_for",
    "frequency_buttons",
    "frequency_message",
    "morning_buttons",
    "morning_entries",
    "morning_message",
    "unsent",
]
