"""The account notices nobody can mute: the subscription running out, the
adverts an ended one stopped, the cabinet's own troubles, a broken Facebook
connection, Meta holding new adverts until the profile is confirmed.

Each is claimed in the journal before it is sent and committed after, as in
:mod:`app.modules.notifications.services.announce`.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from telegramkit import BotClient, Button

from app.common.dates import date_format
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.ads.models import LapseHold
from app.modules.billing.models import Subscription
from app.modules.businesses.selectors import business_timezone
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors import ActionRequired
from app.modules.integrations.selectors.standing import stopped_clause
from app.modules.leads.selectors import held_lead_count
from app.modules.notifications.constants import MAX_TROUBLES_PER_SWEEP, NoticeKind
from app.modules.notifications.keys import (
    action_required_subject,
    connection_subject,
    expiry_subject,
    lapse_subject,
    reconnected_subject,
    unfrozen_subject,
)
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_for, left_keys
from app.modules.notifications.selectors.inbox import (
    cabinet_inbox,
    not_left,
    page_inbox,
)
from app.modules.notifications.selectors.inbox_guard import is_guard_key
from app.modules.notifications.selectors.inbox_meta import blocked_items
from app.modules.notifications.selectors.inbox_page import inbox_pages
from app.modules.notifications.services.announce import tell
from app.modules.notifications.services.compose import (
    action_required_message,
    ask_button,
    connection_message,
    expiry_message,
    miniapp_button,
    reconnected_message,
    trouble_message,
)
from app.modules.notifications.services.compose_lapse import (
    lapse_cut_off_message,
    lapse_stopped_message,
    unfrozen_message,
)
from core.inbox import InboxItem, by_page, left_key

logger = logging.getLogger(__name__)

STOPPED = "stopped"
# 72 hours after the end: sync and leads stop, a payment brings it back.
CUT_OFF = "cut_off"
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
        # The morning message carries each rise with its three answers.
        "price",
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
    """The adverts an ended subscription stopped, and the cut-off 72 hours on."""
    with override(chat.owner.language):
        message = (
            lapse_cut_off_message() if step == CUT_OFF else lapse_stopped_message()
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


def announce_unfrozen(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    subscription: Subscription,
    change_id: str,
    now: datetime,
) -> bool:
    """The freeze is over: the subscription runs again, its days kept."""
    with override(chat.owner.language):
        message = unfrozen_message(until=_until(db, subscription=subscription))
        told = tell(
            db,
            client=client,
            chat=chat,
            kind=NoticeKind.SUBSCRIPTION,
            subject=unfrozen_subject(change_id=change_id),
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
            if item.kind in SPOKEN_FOR or is_guard_key(item.key):
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


def announce_blocks(db: Session, *, client: BotClient, now: datetime) -> int:
    """An ad account the network stopped, told in the quarter hour it is read.

    The morning's list would say it too, up to a day later - a day of adverts
    that are switched on and shown to nobody. Told under the list's own key,
    so the morning does not say it again; an owner who left the line as it is
    is not told at all. An unpaid account is the stop's own message.
    """
    sent = 0
    accounts = db.scalars(
        select(AdAccount)
        .where(stopped_clause(), AdAccount.is_active.is_(True))
        .options(joinedload(AdAccount.owner))
    ).all()
    for account in accounts:
        items = blocked_items(account=account)
        if not items:
            continue
        chat = chat_for(db, owner=account.owner)
        if chat is None:
            continue
        left = left_keys(db, owner=account.owner, now=now)
        with override(chat.owner.language):
            for item in items:
                if left_key(item.key) in left:
                    continue
                told = tell(
                    db,
                    client=client,
                    chat=chat,
                    kind=NoticeKind.TROUBLE,
                    subject=item.key,
                    text=trouble_message(item=item).text,
                    buttons=ask_button(item_key=item.key),
                    now=now,
                )
                sent += bool(told)
    if sent:
        logger.info("account_block_notices_sent", extra={"count": sent})
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
            text=connection_message(
                held=held_lead_count(db, owner_id=connection.owner_id, now=now)
            ).text,
            now=now,
        )
    return bool(told)


def announce_reconnected(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    connection: ProviderConnection,
    leads: int,
    now: datetime,
) -> bool:
    """The connection the owner was told is down works again, and the leads
    it held are on their way."""
    with override(chat.owner.language):
        told = tell(
            db,
            client=client,
            chat=chat,
            kind=NoticeKind.CONNECTION,
            subject=reconnected_subject(connection_id=connection.id, now=now),
            text=reconnected_message(leads=leads).text,
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
    rows = [
        (item, "")
        for item in not_left(
            db, owner=owner, now=now, items=cabinet_inbox(db, owner=owner, now=now)
        )
    ]
    for view in inbox_pages(db, owner=owner):
        rows += [
            (item, view.page_name)
            for item in not_left(
                db,
                owner=owner,
                now=now,
                items=page_inbox(db, owner=owner, view=view, now=now),
            )
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
    """The plan's price as its owner pays it: dollars abroad, so'm at home."""
    from app.modules.billing.selectors.prices import price_words

    plan = subscription.plan
    if plan.price <= 0:
        return ""
    return price_words(subscription.owner, plan)


__all__ = [
    "CUT_OFF",
    "SPOKEN_FOR",
    "STOPPED",
    "announce_action_required",
    "announce_blocks",
    "announce_connection",
    "announce_expiry",
    "announce_lapse",
    "announce_reconnected",
    "announce_troubles",
    "announce_unfrozen",
]
