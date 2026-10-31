"""The account notices nobody can mute: the subscription running out, the
adverts an ended one stopped, the cabinet's own troubles, a broken Facebook
connection, Meta holding new adverts until the profile is confirmed.

Each is claimed in the journal before it is sent and committed after, as in
:mod:`app.modules.notifications.services.announce`.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session
from telegramkit import BotClient, Button

from app.common.dates import date_format
from app.common.i18n import override
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.ads.models import LapseHold
from app.modules.billing.models import Subscription
from app.modules.businesses.selectors import business_timezone
from app.modules.integrations.models import ProviderConnection
from app.modules.integrations.selectors import ActionRequired
from app.modules.notifications.constants import MAX_TROUBLES_PER_SWEEP, NoticeKind
from app.modules.notifications.keys import (
    action_required_subject,
    connection_subject,
    expiry_subject,
    lapse_subject,
)
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import deadline_text
from app.modules.notifications.selectors.inbox import cabinet_inbox, page_inbox
from app.modules.notifications.selectors.inbox_page import inbox_pages
from app.modules.notifications.services.announce import tell
from app.modules.notifications.services.compose import (
    action_required_message,
    ask_button,
    connection_message,
    expiry_message,
    miniapp_button,
    trouble_message,
)
from app.modules.notifications.services.compose_lapse import (
    lapse_last_warning_message,
    lapse_stopped_message,
)
from core.inbox import InboxItem, by_page

logger = logging.getLogger(__name__)

STOPPED = "stopped"
LAST = "last"
# Kinds another message already carries, or that the cabinet answers live.
SPOKEN_FOR: frozenset[str] = frozenset(
    {
        "suggestion",
        "stop",
        "subscription",
        "connection",
        "refusal",
        "wait",
        "watch",
        "frequency",
        "meta_hold",
        "support",
        "feedback",
        "checkup",
    }
)


def announce_expiry(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    subscription: Subscription,
    days: int,
    now: datetime,
) -> bool:
    with override(chat.owner.language):
        message = expiry_message(
            plan_name=subscription.plan.name,
            until=_until(db, subscription=subscription),
            days=days,
            price=_price(subscription=subscription),
        )
        told = tell(
            db,
            client=client,
            chat=chat,
            kind=NoticeKind.SUBSCRIPTION,
            subject=expiry_subject(expires_at=subscription.expires_at, days=days),
            text=message.text,
            buttons=_plans_button(),
            now=now,
        )
    return bool(told)


def announce_lapse(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    hold: LapseHold,
    step: str,
    now: datetime,
) -> bool:
    """The adverts an ended subscription stopped, and a day before removal."""
    with override(chat.owner.language):
        until = deadline_text(db, owner=hold.owner, moment=hold.delete_after)
        message = (
            lapse_last_warning_message(until=until)
            if step == LAST
            else lapse_stopped_message(until=until)
        )
        told = tell(
            db,
            client=client,
            chat=chat,
            kind=NoticeKind.SUBSCRIPTION,
            subject=lapse_subject(hold_id=hold.id, step=step),
            text=message.text,
            buttons=_plans_button(),
            now=now,
        )
    return bool(told)


def announce_troubles(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> int:
    """What the cabinet's own list holds and no other message carries, a few
    lines a day, worst first."""
    sent = 0
    with override(chat.owner.language):
        for item, page in _lines(db, owner=chat.owner, now=now):
            if item.kind in SPOKEN_FOR:
                continue
            if sent >= MAX_TROUBLES_PER_SWEEP:
                break
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.TROUBLE,
                subject=item.key,
                text=trouble_message(item=item, page=page).text,
                buttons=ask_button(item_key=item.key),
                now=now,
            )
            if told is None:
                continue
            if not told:
                break
            sent += 1
    return sent


def announce_connection(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    connection: ProviderConnection,
    now: datetime,
) -> bool:
    with override(chat.owner.language):
        told = tell(
            db,
            client=client,
            chat=chat,
            kind=NoticeKind.CONNECTION,
            subject=connection_subject(
                connection_id=connection.id, status=connection.status, now=now
            ),
            text=connection_message().text,
            now=now,
        )
    return bool(told)


def announce_action_required(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    connection: ProviderConnection,
    hold: ActionRequired,
    now: datetime,
) -> bool:
    if connection.action_required_at is None:
        return False
    with override(chat.owner.language):
        told = tell(
            db,
            client=client,
            chat=chat,
            kind=NoticeKind.ACTION_REQUIRED,
            subject=action_required_subject(
                connection_id=connection.id, since=connection.action_required_at
            ),
            text=action_required_message(
                person=hold.person, manager_url=hold.manager_url
            ).text,
            now=now,
        )
    return bool(told)


def _plans_button() -> tuple[Button, ...]:
    return miniapp_button(route="billing:plans", label="Obunani yangilash")


def _lines(db: Session, *, owner: User, now: datetime) -> list[tuple[InboxItem, str]]:
    rows = [(item, "") for item in cabinet_inbox(db, owner=owner, now=now)]
    for view in inbox_pages(db, owner=owner):
        rows += [
            (item, view.page_name)
            for item in page_inbox(db, owner=owner, view=view, now=now)
        ]
    return by_page(rows)


def _until(db: Session, *, subscription: Subscription) -> str:
    zone = business_timezone(db, owner=subscription.owner)
    moment = subscription.expires_at
    if zone:
        try:
            moment = moment.astimezone(ZoneInfo(zone))
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("unknown business timezone", extra={"zone": zone})
    return date_format(moment, "j F Y")


def _price(*, subscription: Subscription) -> str:
    plan = subscription.plan
    if plan.price <= 0:
        return ""
    return format_minor(amount_minor=plan.price, currency=plan.currency, places=0)


__all__ = [
    "LAST",
    "SPOKEN_FOR",
    "STOPPED",
    "announce_action_required",
    "announce_connection",
    "announce_expiry",
    "announce_lapse",
    "announce_troubles",
]
