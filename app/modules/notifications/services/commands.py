"""The customer bot's report commands, and the buttons under the daily list.

``/hisobot`` sends yesterday's list again, ``/bugun`` today's so far in the
same shape. A pair's button rewrites the list in place into that pair's day,
and «Ro'yxat» brings the list back. Nothing here is journalled: each answers
something the reader just did.
"""

from datetime import datetime

from sqlalchemy.orm import Session
from telegramkit import BotClient, Button, ButtonPress

from app.common.i18n import override
from app.modules.billing.selectors import has_live_subscription
from app.modules.chat.selectors import cabinet_clock, current_day
from app.modules.notifications.constants import CALLBACK_DAILY_LIST
from app.modules.notifications.keys import pair_digest, read_daily_press
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_by_id
from app.modules.notifications.selectors.daily import day_reports
from app.modules.notifications.services.compose import Message, escaped, miniapp_button
from app.modules.notifications.services.compose_daily import (
    list_buttons,
    list_message,
    part_count,
)
from app.modules.notifications.services.compose_day_pair import (
    pair_buttons,
    pair_message,
)
from app.modules.notifications.services.send import answer, edit, send_to
from core.chat.day_report import DailyReport


def send_yesterday(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> str:
    """``/hisobot``: yesterday's list, as the morning sent it."""
    if not _entitled(db, client=client, chat=chat, now=now):
        return "not_entitled"
    reports = day_reports(db, owner=chat.owner, now=now)
    return _send_reports(
        db,
        client=client,
        chat=chat,
        reports=reports,
        empty="Kecha reklamaga pul sarflanmagan.",
        now=now,
    )


def send_today(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> str:
    """``/bugun``: today so far, said to be so."""
    if not _entitled(db, client=client, chat=chat, now=now):
        return "not_entitled"
    clock = cabinet_clock(db, owner=chat.owner)
    reports = (
        day_reports(
            db, owner=chat.owner, now=now, day=current_day(account=clock, now=now)
        )
        if clock is not None
        else []
    )
    return _send_reports(
        db,
        client=client,
        chat=chat,
        reports=reports,
        empty="Bugun hali reklamaga pul sarflanmagan.",
        now=now,
    )


def is_daily_press(data: str) -> bool:
    return read_daily_press(data) is not None


def handle_daily_press(
    db: Session, *, client: BotClient, press: ButtonPress, now: datetime
) -> str:
    """A pair's button, or «Ro'yxat», under a daily message: the message is
    rewritten in place. Only the chat it was sent to may press it."""
    chat = chat_by_id(db, chat_id=press.chat_id)
    if chat is None or not chat.is_active:
        answer(client=client, query_id=press.query_id, text="Telegram ulanmagan.")
        return "unlinked"
    parsed = read_daily_press(press.data)
    with override(chat.owner.language):
        if press.sender.id != chat.chat_id:
            answer(
                client=client,
                query_id=press.query_id,
                text="Bu tugma sizga tegishli emas.",
                alert=True,
            )
            return "stranger"
        if parsed is None:
            answer(client=client, query_id=press.query_id)
            return "ignored"
        action, day, value = parsed
        reports = day_reports(db, owner=chat.owner, now=now, day=day)
        reply = _reply(reports=reports, action=action, value=value)
        if reply is None:
            answer(
                client=client,
                query_id=press.query_id,
                text="Bu hisobot endi ochilmaydi.",
            )
            return "daily_gone"
    message, buttons, outcome = reply
    answer(client=client, query_id=press.query_id)
    edit(
        client=client,
        chat_id=chat.chat_id,
        message_id=press.message_id,
        text=message.text,
        buttons=buttons,
    )
    return outcome


def _reply(
    *, reports: list[DailyReport], action: str, value: str
) -> tuple[Message, tuple[Button, ...], str] | None:
    if not reports:
        return None
    if action == CALLBACK_DAILY_LIST:
        part = min(int(value), part_count(reports) - 1)
        return (
            list_message(reports=reports, part=part),
            list_buttons(reports=reports, part=part),
            "daily_list",
        )
    index = next(
        (
            place
            for place, report in enumerate(reports)
            if pair_digest(report.pair) == value
        ),
        None,
    )
    if index is None:
        return None
    return (
        pair_message(report=reports[index], number=index + 1),
        pair_buttons(reports=reports, index=index),
        "daily_pair",
    )


def _send_reports(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    reports: list[DailyReport],
    empty: str,
    now: datetime,
) -> str:
    if all(report.is_quiet for report in reports):
        send_to(db, client=client, chat=chat, text=escaped(empty), now=now)
        return "report_quiet"
    for part in range(part_count(reports)):
        send_to(
            db,
            client=client,
            chat=chat,
            text=list_message(reports=reports, part=part).text,
            buttons=list_buttons(reports=reports, part=part),
            now=now,
        )
    return "report_sent"


def _entitled(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> bool:
    if has_live_subscription(db, owner=chat.owner):
        return True
    send_to(
        db,
        client=client,
        chat=chat,
        text=escaped(
            "Obuna faol emas, shuning uchun hisobotni ko'rsata olmayman. "
            "Obunani yangilasangiz — davom etamiz."
        ),
        buttons=miniapp_button(route="billing:plans", label="Obunani yangilash"),
        now=now,
    )
    return False


__all__ = ["handle_daily_press", "is_daily_press", "send_today", "send_yesterday"]
