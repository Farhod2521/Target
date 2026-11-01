"""The morning's daily report and Monday's weekly one.

**Figures only.** No model reads either: each says what was spent, and each
pair's button what its goals brought and what one cost, a week against the week
before. Somebody who wants to know whether a figure is good asks the assistant.

**Hourly, on each owner's clock.** The day ends at a different hour in every
account's timezone, and the night's re-read finishes at a different hour for
every account, so the audience is asked every hour and each owner is sent
their report once - when the night is done, or at the latest hour anyway. One
sent early says so, and is edited in place when the night does finish.
"""

import logging
from datetime import date, datetime
from typing import Final, Literal

from sqlalchemy.orm import Session
from telegramkit import BotClient

from app.common import timezone
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.chat.selectors import (
    cabinet_clock,
    night_has_passed,
    report_day,
    week_bounds,
    week_is_final,
)
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import (
    DAILY_REPORT_HOUR,
    DAILY_REPORT_LATEST_HOUR,
    WEEKLY_REPORT_HOUR,
    WEEKLY_REPORT_LATEST_HOUR,
    NoticeKind,
)
from app.modules.notifications.keys import (
    daily_done_subject,
    daily_final_subject,
    daily_subject,
    weekly_done_subject,
    weekly_final_subject,
    weekly_subject,
)
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_for, chats_wanting
from app.modules.notifications.selectors.daily import day_book, week_book
from app.modules.notifications.selectors.queue import (
    has_been_announced,
    sent_message_id,
)
from app.modules.notifications.services.compose_day_pair import day_view
from app.modules.notifications.services.journal import claim, settle, stamp
from app.modules.notifications.services.send import edit, send_to
from core.chat.day_report import DayBook

logger = logging.getLogger(__name__)

Outcome = Literal["sent", "settled", "owed"]
SENT: Final[Outcome] = "sent"
SETTLED: Final[Outcome] = "settled"
OWED: Final[Outcome] = "owed"
MONDAY: Final = 0


# -- the daily list -------------------------------------------------------------


def daily_report_audience(db: Session, *, now: datetime) -> list[str]:
    """The owners whose finished day is ready to be told, this hour."""
    if not is_configured():
        return []
    owners: list[str] = []
    for chat in db.scalars(chats_wanting(db, kind=NoticeKind.DAILY_REPORT)).all():
        account = cabinet_clock(db, owner=chat.owner)
        if account is None:
            continue
        subject = daily_done_subject(day=report_day(account=account, now=now))
        if has_been_announced(
            db, owner=chat.owner, kind=NoticeKind.DAILY_REPORT, subject=subject
        ):
            continue
        hour = timezone.localtime(now, account.tzinfo()).hour
        if hour < DAILY_REPORT_HOUR:
            continue
        late = hour >= DAILY_REPORT_LATEST_HOUR
        if late or night_has_passed(db, owner=chat.owner, account=account, now=now):
            owners.append(str(chat.owner_id))
    return owners


def deliver_daily_report_for(db: Session, *, owner: User, now: datetime) -> bool:
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_daily_report or not is_configured():
        return False
    with bot() as client:
        return announce_daily(db, client=client, chat=chat, now=now)


def announce_daily(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> bool:
    """The day's one message. A day nothing was spent on is marked done
    without one: a phone buzzing to say nothing happened is a phone taught to
    ignore the next one."""
    with override(chat.owner.language):
        book = day_book(db, owner=chat.owner, now=now)
    if book is None:
        return False
    outcome = (
        SETTLED
        if book.is_quiet
        else _announce_book(db, client=client, chat=chat, book=book, now=now)
    )
    if outcome != OWED:
        settle(
            db,
            chat=chat,
            kind=NoticeKind.DAILY_REPORT,
            subject=daily_done_subject(day=book.day),
            now=now,
        )
        if book.final:
            _settle_final(db, chat=chat, book=book, now=now)
    db.commit()
    return outcome == SENT


def _settle_final(
    db: Session, *, chat: TelegramChat, book: DayBook, now: datetime
) -> None:
    settle(
        db,
        chat=chat,
        kind=NoticeKind.DAILY_REPORT,
        subject=daily_final_subject(day=book.day),
        now=now,
    )


def _announce_book(
    db: Session, *, client: BotClient, chat: TelegramChat, book: DayBook, now: datetime
) -> Outcome:
    subject = daily_subject(day=book.day, part=0)
    if has_been_announced(
        db, owner=chat.owner, kind=NoticeKind.DAILY_REPORT, subject=subject
    ):
        return SETTLED
    notice = claim(db, chat=chat, kind=NoticeKind.DAILY_REPORT, subject=subject)
    if notice is None:
        return SETTLED
    with override(chat.owner.language):
        message, buttons = day_view(book=book)
    message_id = send_to(
        db, client=client, chat=chat, text=message.text, buttons=buttons, now=now
    )
    stamp(db, notice=notice, message_id=message_id, now=now)
    db.commit()
    return SENT if message_id else OWED


# -- a day sent before its night was over ----------------------------------------


def unfinished_report_audience(db: Session, *, now: datetime) -> list[str]:
    """The owners whose morning message said its figures were not final, and
    whose night has finished since."""
    if not is_configured():
        return []
    owners: list[str] = []
    for chat in db.scalars(chats_wanting(db, kind=NoticeKind.DAILY_REPORT)).all():
        account = cabinet_clock(db, owner=chat.owner)
        if account is None:
            continue
        day = report_day(account=account, now=now)
        if _unfinished_message(db, chat=chat, day=day) and night_has_passed(
            db, owner=chat.owner, account=account, now=now
        ):
            owners.append(str(chat.owner_id))
    return owners


def _unfinished_message(db: Session, *, chat: TelegramChat, day: date) -> int:
    """The day's message, while it still stands unfinished; otherwise 0."""
    if has_been_announced(
        db,
        owner=chat.owner,
        kind=NoticeKind.DAILY_REPORT,
        subject=daily_final_subject(day=day),
    ):
        return 0
    return sent_message_id(
        db,
        owner=chat.owner,
        kind=NoticeKind.DAILY_REPORT,
        subject=daily_subject(day=day, part=0),
    )


def finish_daily_report_for(db: Session, *, owner: User, now: datetime) -> bool:
    """Put the finished figures into the message sent without them.

    Edited rather than sent again: the reader has one report for the day, and
    a second buzz would say nothing new about most of it.
    """
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_daily_report or not is_configured():
        return False
    with override(chat.owner.language):
        book = day_book(db, owner=owner, now=now)
    if book is None or not book.final:
        return False
    message_id = _unfinished_message(db, chat=chat, day=book.day)
    if not message_id:
        return False
    with override(chat.owner.language):
        message, buttons = day_view(book=book)
    with bot() as client:
        edit(
            client=client,
            chat_id=chat.chat_id,
            message_id=message_id,
            text=message.text,
            buttons=buttons,
        )
    _settle_final(db, chat=chat, book=book, now=now)
    db.commit()
    return True


# -- the week -------------------------------------------------------------------


def report_audience(db: Session, *, now: datetime) -> list[str]:
    """The owners whose Monday morning it is, and whose week is not told yet."""
    if not is_configured():
        return []
    owners: list[str] = []
    for chat in db.scalars(chats_wanting(db, kind=NoticeKind.REPORT)).all():
        account = cabinet_clock(db, owner=chat.owner)
        if account is None:
            continue
        local = timezone.localtime(now, account.tzinfo())
        if local.weekday() != MONDAY or local.hour < WEEKLY_REPORT_HOUR:
            continue
        since, _until = week_bounds(today=local.date())
        if has_been_announced(
            db,
            owner=chat.owner,
            kind=NoticeKind.REPORT,
            subject=weekly_done_subject(since=since),
        ):
            continue
        late = local.hour >= WEEKLY_REPORT_LATEST_HOUR
        if late or night_has_passed(db, owner=chat.owner, account=account, now=now):
            owners.append(str(chat.owner_id))
    return owners


def deliver_report_for(db: Session, *, owner: User, now: datetime) -> bool:
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_report or not is_configured():
        return False
    with bot() as client:
        return announce_report(db, client=client, chat=chat, now=now)


def announce_report(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> bool:
    """The week's one message. A week nothing was spent on is marked done
    without one, like a quiet day."""
    with override(chat.owner.language):
        book = week_book(db, owner=chat.owner, now=now)
    if book is None:
        return False
    outcome = (
        SETTLED
        if book.is_quiet
        else _announce_week(db, client=client, chat=chat, book=book, now=now)
    )
    if outcome != OWED:
        settle(
            db,
            chat=chat,
            kind=NoticeKind.REPORT,
            subject=weekly_done_subject(since=book.day),
            now=now,
        )
        if book.final:
            _settle_week_final(db, chat=chat, book=book, now=now)
    db.commit()
    return outcome == SENT


def _settle_week_final(
    db: Session, *, chat: TelegramChat, book: DayBook, now: datetime
) -> None:
    settle(
        db,
        chat=chat,
        kind=NoticeKind.REPORT,
        subject=weekly_final_subject(since=book.day),
        now=now,
    )


def _announce_week(
    db: Session, *, client: BotClient, chat: TelegramChat, book: DayBook, now: datetime
) -> Outcome:
    subject = weekly_subject(since=book.day)
    if has_been_announced(
        db, owner=chat.owner, kind=NoticeKind.REPORT, subject=subject
    ):
        return SETTLED
    notice = claim(db, chat=chat, kind=NoticeKind.REPORT, subject=subject)
    if notice is None:
        return SETTLED
    with override(chat.owner.language):
        message, buttons = day_view(book=book)
    message_id = send_to(
        db, client=client, chat=chat, text=message.text, buttons=buttons, now=now
    )
    stamp(db, notice=notice, message_id=message_id, now=now)
    db.commit()
    return SENT if message_id else OWED


def unfinished_week_audience(db: Session, *, now: datetime) -> list[str]:
    """The owners whose Monday message said its figures were not final, and
    whose week has settled since."""
    if not is_configured():
        return []
    owners: list[str] = []
    for chat in db.scalars(chats_wanting(db, kind=NoticeKind.REPORT)).all():
        account = cabinet_clock(db, owner=chat.owner)
        if account is None:
            continue
        today = timezone.localtime(now, account.tzinfo()).date()
        since, until = week_bounds(today=today)
        if _unfinished_week(db, chat=chat, since=since) and week_is_final(
            db, owner=chat.owner, account=account, now=now, until=until
        ):
            owners.append(str(chat.owner_id))
    return owners


def _unfinished_week(db: Session, *, chat: TelegramChat, since: date) -> int:
    """The week's message, while it still stands unfinished; otherwise 0."""
    if has_been_announced(
        db,
        owner=chat.owner,
        kind=NoticeKind.REPORT,
        subject=weekly_final_subject(since=since),
    ):
        return 0
    return sent_message_id(
        db,
        owner=chat.owner,
        kind=NoticeKind.REPORT,
        subject=weekly_subject(since=since),
    )


def finish_weekly_report_for(db: Session, *, owner: User, now: datetime) -> bool:
    """Put the finished figures into the week's message, as for a day."""
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_report or not is_configured():
        return False
    with override(chat.owner.language):
        book = week_book(db, owner=owner, now=now)
    if book is None or not book.final:
        return False
    message_id = _unfinished_week(db, chat=chat, since=book.day)
    if not message_id:
        return False
    with override(chat.owner.language):
        message, buttons = day_view(book=book)
    with bot() as client:
        edit(
            client=client,
            chat_id=chat.chat_id,
            message_id=message_id,
            text=message.text,
            buttons=buttons,
        )
    _settle_week_final(db, chat=chat, book=book, now=now)
    db.commit()
    return True


__all__ = [
    "announce_daily",
    "announce_report",
    "daily_report_audience",
    "deliver_daily_report_for",
    "deliver_report_for",
    "finish_daily_report_for",
    "finish_weekly_report_for",
    "report_audience",
    "unfinished_report_audience",
    "unfinished_week_audience",
]
