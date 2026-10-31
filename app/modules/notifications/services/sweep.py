"""The passes that find what is owed and send it.

**A sweep, not a push.** A ``send`` inside the agent's or the mirror's
services fires once, and if the process dies between the write and the
send nothing ever notices. The journal is the sweep's state, so a pass that
runs twice sends once and a pass that never ran catches up on the next.

**Which accounts are owed anything is asked once, not once per chat.** A
few set reads name the handful of owners with something open; the per-owner
reads then run only for them. The sets are wider than the truth - a filter,
never the decision.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from telegramkit import BotClient

from app.modules.accounts.models import User
from app.modules.ads.selectors.lapse import last_warning_due, open_holds
from app.modules.agent.selectors.launch_watch import owners_with_launches
from app.modules.billing.constants import EXPIRY_REMINDER_DAYS
from app.modules.billing.selectors import expiring_subscriptions
from app.modules.chat.selectors import cabinet_clock
from app.modules.integrations.selectors import (
    action_required_connections,
    broken_meta_connections,
    local_hours,
    meta_action_required,
)
from app.modules.notifications.bot import (
    bot,
    is_configured,
    sends_expiry_notices,
    sends_mandatory_notices,
)
from app.modules.notifications.constants import (
    DAILY_REPORT_HOUR,
    TROUBLE_HOUR,
    NoticeKind,
)
from app.modules.notifications.selectors import (
    FLAG_FOR,
    active_chats,
    chat_for,
    chats_wanting,
)
from app.modules.notifications.selectors.queue import (
    owners_with_fresh_outcomes,
    owners_with_open_suggestions,
    owners_with_rejected_ads,
)
from app.modules.notifications.services.announce import (
    announce_outcomes,
    announce_rejections,
    announce_stops,
    announce_suggestions,
    announce_watches,
)
from app.modules.notifications.services.announce_account import (
    LAST,
    STOPPED,
    announce_action_required,
    announce_connection,
    announce_expiry,
    announce_lapse,
    announce_troubles,
)

logger = logging.getLogger(__name__)


def deliver_notices(db: Session, *, now: datetime) -> int:
    """Everything owed to every linked phone, every quarter hour.

    One client for the whole pass, so a deployment with no token finds out
    once rather than per message. The broken connection rides along: it
    costs something every hour it waits.
    """
    if not is_configured():
        return 0

    proposing = owners_with_open_suggestions(db, now=now)
    judged = owners_with_fresh_outcomes(db, now=now)
    refused = owners_with_rejected_ads(db)
    launching = owners_with_launches(db)
    asleep = _asleep(db, owner_ids={*proposing, *judged, *launching}, now=now)

    sent = 0
    with bot() as client:
        for chat in db.scalars(chats_wanting(db, kind=NoticeKind.SUGGESTION)).all():
            if str(chat.owner_id) in asleep:
                continue
            if chat.owner_id in proposing:
                sent += announce_suggestions(db, client=client, chat=chat, now=now)
            if chat.owner_id in judged:
                sent += announce_outcomes(db, client=client, chat=chat, now=now)
        for chat in db.scalars(chats_wanting(db, kind=NoticeKind.REJECTION)).all():
            if chat.owner_id in refused:
                sent += announce_rejections(db, client=client, chat=chat, now=now)
        sent += announce_watches(
            db, client=client, now=now, launching=launching, asleep=asleep
        )
        sent += announce_stops(db, client=client, now=now)
        sent += _announce_broken_connections(db, client=client, now=now)
        sent += _announce_action_required(db, client=client, now=now)

    if sent:
        logger.info("telegram_notices_sent", extra={"count": sent})
    return sent


def deliver_expiry_notices(db: Session, *, now: datetime) -> int:
    """Warn every account whose subscription runs out in three days, and in one.

    A day-wide window per step because this runs once a day. No preference
    column - being locked out unannounced is not something anybody asked
    for by muting proposals - so the deployment switch is asked instead.
    """
    if not is_configured() or not sends_expiry_notices():
        return 0

    sent = 0
    with bot() as client:
        for days in EXPIRY_REMINDER_DAYS:
            start = now + timedelta(days=days)
            for subscription in expiring_subscriptions(
                db, start=start, end=start + timedelta(days=1)
            ):
                chat = chat_for(db, owner=subscription.owner)
                if chat is not None:
                    sent += announce_expiry(
                        db,
                        client=client,
                        chat=chat,
                        subscription=subscription,
                        days=days,
                        now=now,
                    )

    if sent:
        logger.info("subscription_expiry_notices_sent", extra={"count": sent})
    return sent


def deliver_lapse_notices(db: Session, *, now: datetime) -> int:
    """Tell the owners whose adverts an ended subscription stopped, and again a
    day before they are removed. The journal holds one message per step."""
    if not is_configured() or not sends_expiry_notices():
        return 0

    sent = 0
    with bot() as client:
        for hold in open_holds(db):
            chat = chat_for(db, owner=hold.owner)
            if chat is None:
                continue
            step = LAST if last_warning_due(hold=hold, now=now) else STOPPED
            sent += announce_lapse(
                db, client=client, chat=chat, hold=hold, step=step, now=now
            )

    if sent:
        logger.info("lapse_notices_sent", extra={"count": sent})
    return sent


def deliver_troubles(db: Session, *, now: datetime) -> int:
    """The cabinet's own list, once a day in each owner's morning.

    Hourly and driven from the chats: each owner hears it in the hour
    ``TROUBLE_HOUR`` starts on their clock. Nothing it carries gets worse
    inside a day; the one trouble that does - a broken connection - keeps
    the quarter-hourly pass.
    """
    if not is_configured() or not sends_mandatory_notices():
        return 0

    sent = 0
    with bot() as client:
        for chat in db.scalars(active_chats()).all():
            if _is_trouble_hour(db, owner=chat.owner, now=now):
                sent += announce_troubles(db, client=client, chat=chat, now=now)

    if sent:
        logger.info("telegram_trouble_notices_sent", extra={"count": sent})
    return sent


def _announce_action_required(db: Session, *, client: BotClient, now: datetime) -> int:
    """Every account Meta holds until its owner confirms the profile. The
    rejections preference is asked, the deployment switch is not."""
    flag = FLAG_FOR[NoticeKind.ACTION_REQUIRED]
    sent = 0
    for connection in action_required_connections(db):
        chat = chat_for(db, owner=connection.owner)
        if chat is None or not getattr(chat, flag):
            continue
        hold = meta_action_required(db, owner=connection.owner)
        if hold is None:
            continue
        sent += announce_action_required(
            db, client=client, chat=chat, connection=connection, hold=hold, now=now
        )
    return sent


def _announce_broken_connections(
    db: Session, *, client: BotClient, now: datetime
) -> int:
    """Every account whose Facebook connection stopped working. Nobody can
    mute it, so the deployment switch for such notices is asked."""
    if not sends_mandatory_notices():
        return 0
    sent = 0
    for connection in broken_meta_connections(db):
        chat = chat_for(db, owner=connection.owner)
        if chat is not None:
            sent += announce_connection(
                db, client=client, chat=chat, connection=connection, now=now
            )
    return sent


def _asleep(db: Session, *, owner_ids: set[object], now: datetime) -> set[str]:
    """The owners for whom it is still before the morning report: the agent
    proposes in their night, and a card at three wakes them for nothing."""
    return {
        owner_id
        for owner_id, hour in local_hours(db, owner_ids=owner_ids, now=now).items()
        if hour < DAILY_REPORT_HOUR
    }


def _is_trouble_hour(db: Session, *, owner: User, now: datetime) -> bool:
    account = cabinet_clock(db, owner=owner)
    zone = account.tzinfo() if account is not None else UTC
    return now.astimezone(zone).hour == TROUBLE_HOUR


__all__ = [
    "deliver_expiry_notices",
    "deliver_lapse_notices",
    "deliver_notices",
    "deliver_troubles",
]
