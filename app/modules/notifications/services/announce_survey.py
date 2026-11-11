"""The survey owed today, asked in the bot inside the asking hours.

Hourly, a task per linked owner whose clock is between the first and the
last asking hour; a day is asked once, and never again on a day the owner
already answered one - in the cabinet, the mini app or here.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import (
    SURVEY_FIRST_HOUR,
    SURVEY_LAST_HOUR,
    NoticeKind,
)
from app.modules.notifications.selectors import active_chats, chat_for
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.survey_bot import resend_survey, start_survey
from app.modules.notifications.services.survey_state import local_now
from app.modules.surveys.selectors.due import answered_since, due_survey


def survey_audience(db: Session, *, now: datetime) -> list[str]:
    """The linked owners inside the asking hours on their own clock. Staff
    come too, and are asked only a survey that picked them by name."""
    owners: list[str] = []
    for chat in db.scalars(active_chats()).all():
        hour = local_now(db, owner=chat.owner, now=now).hour
        if SURVEY_FIRST_HOUR <= hour < SURVEY_LAST_HOUR:
            owners.append(str(chat.owner_id))
    return owners


def deliver_survey_for(db: Session, *, owner: User, now: datetime) -> str:
    chat = chat_for(db, owner=owner)
    if chat is None or not is_configured():
        return "unlinked"
    local = local_now(db, owner=owner, now=now)
    morning = local.replace(hour=0, minute=0, second=0, microsecond=0)
    with override(owner.language):
        if answered_since(db, user=owner, since=morning):
            return "answered_today"
        due = due_survey(db, user=owner, language=owner.language)
        if due is None:
            return "none"
        notice = claim(
            db,
            chat=chat,
            kind=NoticeKind.SURVEY,
            subject=f"day:{local.date().isoformat()}",
        )
        if notice is None:
            return "asked"
        with bot() as client:
            sent = start_survey(db, client=client, chat=chat, due=due, now=now)
        stamp(db, notice=notice, message_id=sent, now=now)
    db.commit()
    return "sent" if sent else "failed"


def resend_survey_for(db: Session, *, owner: User, token: str, now: datetime) -> str:
    chat = chat_for(db, owner=owner)
    if chat is None or not is_configured():
        return "unlinked"
    with override(owner.language), bot() as client:
        return resend_survey(db, client=client, chat=chat, token=token, now=now)


__all__ = ["deliver_survey_for", "resend_survey_for", "survey_audience"]
