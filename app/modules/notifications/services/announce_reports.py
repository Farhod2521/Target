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
from collections.abc import Callable
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
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.compose_day_pair import day_views
from app.modules.notifications.services.journal import claim, settle, stamp
from app.modules.notifications.services.send import edit, send_to
from core.chat.day_report import DayBook

logger = logging.getLogger(__name__)

Outcome = Literal["sent", "settled", "owed"]
SENT: Final[Outcome] = "sent"
SETTLED: Final[Outcome] = "settled"
OWED: Final[Outcome] = "owed"
MONDAY: Final = 0
# What a message of the list says once the list needs one message fewer.
LIST_MOVED: Final = "Ro'yxat yuqoridagi xabarga jamlandi."


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
    """The day's messages. A day nothing was spent on is marked done
    without any: a phone buzzing to say nothing happened is a phone taught to
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
    return _send_parts(
        db,
        client=client,
        chat=chat,
        book=book,
        kind=NoticeKind.DAILY_REPORT,
        subject_of=lambda part: daily_subject(day=book.day, part=part),
        now=now,
    )


def _send_parts(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    book: DayBook,
    kind: NoticeKind,
    subject_of: Callable[[int], str],
    now: datetime,
) -> Outcome:
    """Every message of the list not sent yet, each journalled on its own: a
    second one Telegram refused is owed without the first going out twice."""
    with override(chat.owner.language):
        views = day_views(book=book)
    outcome = SETTLED
    for part, (message, buttons) in enumerate(views):
        subject = subject_of(part)
        if has_been_announced(db, owner=chat.owner, kind=kind, subject=subject):
            continue
        notice = claim(db, chat=chat, kind=kind, subject=subject)
        if notice is None:
            continue
        message_id = send_to(
            db, client=client, chat=chat, text=message.text, buttons=buttons, now=now
        )
        stamp(db, notice=notice, message_id=message_id, now=now)
        db.commit()
        if not message_id:
            return OWED
        outcome = SENT
    return outcome


def _finish_parts(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    book: DayBook,
    kind: NoticeKind,
    subject_of: Callable[[int], str],
    now: datetime,
) -> None:
    """Finished figures into the messages already out. A list that grew gets
    its new message; a message a shorter list no longer needs says so."""
    with override(chat.owner.language):
        views = day_views(book=book)
    for part, (message, buttons) in enumerate(views):
        message_id = sent_message_id(
            db, owner=chat.owner, kind=kind, subject=subject_of(part)
        )
        if message_id:
            edit(
                client=client,
                chat_id=chat.chat_id,
                message_id=message_id,
                text=message.text,
                buttons=buttons,
            )
    _send_parts(
        db,
        client=client,
        chat=chat,
        book=book,
        kind=kind,
        subject_of=subject_of,
        now=now,
    )
    part = len(views)
    while message_id := sent_message_id(
        db, owner=chat.owner, kind=kind, subject=subject_of(part)
    ):
        edit(
            client=client,
            chat_id=chat.chat_id,
            message_id=message_id,
            text=escaped(LIST_MOVED),
        )
        part += 1


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
    """The day's first message, while the day stands unfinished; otherwise 0."""
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
    """Put the finished figures into the messages sent without them.

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
    if not _unfinished_message(db, chat=chat, day=book.day):
        return False
    with bot() as client:
        _finish_parts(
            db,
            client=client,
            chat=chat,
            book=book,
            kind=NoticeKind.DAILY_REPORT,
            subject_of=lambda part: daily_subject(day=book.day, part=part),
            now=now,
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
    """The week's messages. A week nothing was spent on is marked done
    without any, like a quiet day."""
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
    return _send_parts(
        db,
        client=client,
        chat=chat,
        book=book,
        kind=NoticeKind.REPORT,
        subject_of=lambda part: weekly_subject(since=book.day, part=part),
        now=now,
    )


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
    """The week's first message, while the week stands unfinished; otherwise 0."""
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
        subject=weekly_subject(since=since, part=0),
    )


def finish_weekly_report_for(db: Session, *, owner: User, now: datetime) -> bool:
    """Put the finished figures into the week's messages, as for a day."""
    chat = chat_for(db, owner=owner)
    if chat is None or not chat.notify_report or not is_configured():
        return False
    with override(chat.owner.language):
        book = week_book(db, owner=owner, now=now)
    if book is None or not book.final:
        return False
    if not _unfinished_week(db, chat=chat, since=book.day):
        return False
    with bot() as client:
        _finish_parts(
            db,
            client=client,
            chat=chat,
            book=book,
            kind=NoticeKind.REPORT,
            subject_of=lambda part: weekly_subject(since=book.day, part=part),
            now=now,
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
