"""The morning's daily report and Monday's weekly one.

**Figures only.** No model reads either: the daily list says what each pair
spent, what it brought and what one cost, and the week's message its figures
against the week before. Somebody who wants to know whether a figure is good
asks the assistant.

**Hourly, on each owner's clock.** The day ends at a different hour in every
account's timezone, and the night's re-read finishes at a different hour for
every account, so the audience is asked every hour and each owner is sent
their report once - when the night is done, or at the latest hour anyway.
"""

import logging
from datetime import datetime
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
    weekly_reports,
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
    daily_subject,
    report_subject,
    weekly_done_subject,
)
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_for, chats_wanting
from app.modules.notifications.selectors.daily import day_reports
from app.modules.notifications.selectors.queue import has_been_announced
from app.modules.notifications.services.compose import miniapp_button
from app.modules.notifications.services.compose_daily import (
    list_buttons,
    list_message,
    part_count,
)
from app.modules.notifications.services.compose_weekly import weekly_message
from app.modules.notifications.services.journal import claim, settle, stamp
from app.modules.notifications.services.send import send_to
from core.chat.day_report import DailyReport
from core.chat.report import WeeklyReport

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
    """The day's list, five pairs a message. A day nothing was spent on is
    marked done without a message: a phone buzzing to say nothing happened is
    a phone taught to ignore the next one."""
    with override(chat.owner.language):
        reports = day_reports(db, owner=chat.owner, now=now)
    if not reports:
        return False
    if all(report.is_quiet for report in reports):
        outcomes = [SETTLED]
    else:
        outcomes = [
            _announce_part(
                db, client=client, chat=chat, reports=reports, part=part, now=now
            )
            for part in range(part_count(reports))
        ]
    if OWED not in outcomes:
        settle(
            db,
            chat=chat,
            kind=NoticeKind.DAILY_REPORT,
            subject=daily_done_subject(day=reports[0].day),
            now=now,
        )
    db.commit()
    return SENT in outcomes


def _announce_part(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    reports: list[DailyReport],
    part: int,
    now: datetime,
) -> Outcome:
    subject = daily_subject(day=reports[0].day, part=part)
    if has_been_announced(
        db, owner=chat.owner, kind=NoticeKind.DAILY_REPORT, subject=subject
    ):
        return SETTLED
    notice = claim(db, chat=chat, kind=NoticeKind.DAILY_REPORT, subject=subject)
    if notice is None:
        return SETTLED
    with override(chat.owner.language):
        message = list_message(reports=reports, part=part)
        buttons = list_buttons(reports=reports, part=part)
    message_id = send_to(
        db, client=client, chat=chat, text=message.text, buttons=buttons, now=now
    )
    stamp(db, notice=notice, message_id=message_id, now=now)
    db.commit()
    return SENT if message_id else OWED


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
    """Every page's completed week, a message each."""
    with override(chat.owner.language):
        reports = weekly_reports(db, owner=chat.owner, now=now)
    outcomes = [
        _announce_week(db, client=client, chat=chat, report=report, now=now)
        for report in reports
    ]
    clock = cabinet_clock(db, owner=chat.owner)
    if OWED not in outcomes and clock is not None:
        since, _until = week_bounds(
            today=timezone.localtime(now, clock.tzinfo()).date()
        )
        settle(
            db,
            chat=chat,
            kind=NoticeKind.REPORT,
            subject=weekly_done_subject(since=since),
            now=now,
        )
    db.commit()
    return SENT in outcomes


def _announce_week(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    report: WeeklyReport,
    now: datetime,
) -> Outcome:
    if not report.worth_sending:
        return SETTLED
    subject = report_subject(
        since=report.since, until=report.until, now=now, pair=report.pair
    )
    if has_been_announced(
        db, owner=chat.owner, kind=NoticeKind.REPORT, subject=subject
    ):
        return SETTLED
    notice = claim(db, chat=chat, kind=NoticeKind.REPORT, subject=subject)
    if notice is None:
        return SETTLED
    with override(chat.owner.language):
        message = weekly_message(report=report, summary="", advice="")
        buttons = miniapp_button(route="metrics:dashboard", label="Raqamlar")
    message_id = send_to(
        db, client=client, chat=chat, text=message.text, buttons=buttons, now=now
    )
    stamp(db, notice=notice, message_id=message_id, now=now)
    db.commit()
    return SENT if message_id else OWED


__all__ = [
    "announce_daily",
    "announce_report",
    "daily_report_audience",
    "deliver_daily_report_for",
    "deliver_report_for",
    "report_audience",
]
