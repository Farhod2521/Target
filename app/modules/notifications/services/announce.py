"""The ad notices a sweep finds by looking: open proposals, what came of the
approved ones, refused adverts, groups under watch, stopped deliveries.

**Said short, answered in the center.** None of them carries a button that
writes: approving a proposal, pausing a group, raising a budget are made in
the cabinet's center, where the reader sees the state they are deciding on.
The message says what happened and opens the center. The press handlers
come back once the ads action layer is finished.

**Claim, send, stamp, commit - per message.** The journal row is written
before the message goes out, so a worker that dies mid-send leaves a claim
and not a duplicate, and each stamp is committed before the next send so a
pass that dies halfway does not send the first half again.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from telegramkit import BotClient, Button

from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.ads.models import Ad, DeliveryStop
from app.modules.ads.selectors import PageScope, page_scope
from app.modules.ads.selectors.owned import open_stops, stop_campaigns
from app.modules.agent.selectors import card_for
from app.modules.agent.selectors.launch_watch import Watched, watched_groups
from app.modules.notifications.constants import MAX_TROUBLES_PER_SWEEP, NoticeKind
from app.modules.notifications.keys import (
    outcome_subject,
    rejection_subject,
    suggestion_subject,
)
from app.modules.notifications.models import TelegramChat, TelegramNotice
from app.modules.notifications.selectors import chat_for, chats_wanting, left_keys
from app.modules.notifications.selectors.inbox_page import inbox_pages
from app.modules.notifications.selectors.inbox_stops import stop_item
from app.modules.notifications.selectors.inbox_watch import watch_key
from app.modules.notifications.selectors.queue import (
    rejected_ads,
    unannounced_outcomes,
    unannounced_suggestions,
)
from app.modules.notifications.services.compose import (
    center_button,
    outcome_message,
    rejection_message,
    suggestion_notice,
    trouble_message,
)
from app.modules.notifications.services.compose_watch import watch_message
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.send import send_to
from core.inbox import left_key

logger = logging.getLogger(__name__)


def announce_suggestions(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> int:
    """Every open proposal this account was not told about. Returns how many."""
    sent = 0
    with override(chat.owner.language):
        for suggestion in unannounced_suggestions(db, owner=chat.owner, now=now):
            card = card_for(db, owner=chat.owner, suggestion=suggestion)
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.SUGGESTION,
                subject=suggestion_subject(pk=suggestion.id),
                text=suggestion_notice(card=card).text,
                buttons=center_button(item_key=f"suggestion:{suggestion.id}"),
                now=now,
            )
            if told is None:
                continue
            if not told:
                # The chat may have just been switched off by its owner: every
                # remaining message would be claimed and lost.
                break
            sent += 1
    return sent


def announce_outcomes(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> int:
    """Every change judged since this account was last told."""
    sent = 0
    with override(chat.owner.language):
        for suggestion in unannounced_outcomes(db, owner=chat.owner, now=now):
            card = card_for(db, owner=chat.owner, suggestion=suggestion)
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.SUGGESTION,
                subject=outcome_subject(pk=suggestion.id),
                text=outcome_message(card=card).text,
                buttons=center_button(),
                now=now,
            )
            if told is None:
                continue
            if not told:
                break
            sent += 1
    return sent


def announce_rejections(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> int:
    """Adverts the provider refused, each under its page where there are several.

    No buttons: the fix depends on which part was refused, and none of them is
    something to press under a message. The message links to the campaign.
    """
    sent = 0
    scope = page_scope(db, owner=chat.owner)
    with override(chat.owner.language):
        for ad in rejected_ads(db, owner=chat.owner, scope=scope):
            message = rejection_message(
                ad_name=ad.name,
                group_name=ad.adset.name,
                feedback=ad.review_feedback,
                page=_page_named(scope=scope, ad=ad),
            )
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.REJECTION,
                subject=rejection_subject(
                    external_id=ad.external_id, feedback=ad.review_feedback
                ),
                text=message.text,
                now=now,
            )
            if told is None:
                continue
            if not told:
                break
            sent += 1
    return sent


def announce_watches(
    db: Session,
    *,
    client: BotClient,
    now: datetime,
    launching: set[object],
    asleep: set[str],
) -> int:
    """Groups launched here that the watch has something to say about."""
    if not launching:
        return 0
    chats = db.scalars(chats_wanting(db, kind=NoticeKind.LAUNCH_WATCH)).all()
    return sum(
        announce_watch(db, client=client, chat=chat, now=now)
        for chat in chats
        if chat.owner_id in launching and str(chat.owner_id) not in asleep
    )


def announce_watch(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> int:
    """One account's watched groups. The advice is said; the move is the center's."""
    sent = 0
    with override(chat.owner.language):
        for row, page in _watched(db, owner=chat.owner, now=now):
            if sent >= MAX_TROUBLES_PER_SWEEP:
                break
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.LAUNCH_WATCH,
                subject=watch_key(row),
                text=watch_message(row=row, page=page).text,
                now=now,
            )
            if told is None:
                continue
            if not told:
                break
            sent += 1
    return sent


def announce_stops(db: Session, *, client: BotClient, now: datetime) -> int:
    """Every delivery the platform stopped and has not cleared, once each."""
    sent = 0
    open_rows = db.scalars(
        select(DeliveryStop)
        .where(DeliveryStop.cleared_at.is_(None))
        .options(joinedload(DeliveryStop.owner))
    ).all()
    owners = {stop.owner_id: stop.owner for stop in open_rows}
    for owner in owners.values():
        chat = chat_for(db, owner=owner)
        if chat is not None:
            sent += _announce_stops(db, client=client, chat=chat, now=now)
    if sent:
        logger.info("stop_notices_sent", extra={"count": sent})
    return sent


def _announce_stops(
    db: Session, *, client: BotClient, chat: TelegramChat, now: datetime
) -> int:
    sent = 0
    with override(chat.owner.language):
        stops = open_stops(db, owner=chat.owner)
        campaigns = stop_campaigns(db, owner=chat.owner, stops=stops)
        for stop in stops:
            told = tell(
                db,
                client=client,
                chat=chat,
                kind=NoticeKind.STOP,
                subject=f"stop:{stop.id}",
                text=trouble_message(
                    item=stop_item(stop=stop, campaigns=campaigns)
                ).text,
                now=now,
            )
            if told is None:
                continue
            if not told:
                break
            sent += 1
    return sent


def tell(
    db: Session,
    *,
    client: BotClient,
    chat: TelegramChat,
    kind: str,
    subject: str,
    text: str,
    now: datetime,
    buttons: tuple[Button, ...] = (),
) -> bool | None:
    """Claim, send, stamp, commit. None when it was already told or given up
    on; False when Telegram refused this one."""
    notice: TelegramNotice | None = claim(db, chat=chat, kind=kind, subject=subject)
    if notice is None:
        return None
    message_id = send_to(
        db, client=client, chat=chat, text=text, buttons=buttons, now=now
    )
    stamp(db, notice=notice, message_id=message_id, now=now)
    db.commit()
    return bool(message_id)


def _page_named(*, scope: PageScope, ad: Ad) -> str:
    """Which page a refused advert ran from, where the subscription has several.
    Empty when unsure: a guessed name sends the owner to the wrong page."""
    if len(scope.pages) < 2:
        return ""
    return scope.name_of(scope.page_of.get(ad.adset.external_id, ""))


def _watched(db: Session, *, owner: User, now: datetime) -> list[tuple[Watched, str]]:
    """Each watched group once, under the page it runs from."""
    seen: set[str] = set()
    found: list[tuple[Watched, str]] = []
    left = left_keys(db, owner=owner, now=now)
    for view in inbox_pages(db, owner=owner):
        for row in watched_groups(
            db,
            owner=owner,
            accounts=view.accounts,
            now=now,
            hidden_adsets=view.scope.outside,
        ):
            if row.adset_id not in seen and left_key(watch_key(row)) not in left:
                seen.add(row.adset_id)
                found.append((row, view.page_name))
    return found


__all__ = [
    "announce_outcomes",
    "announce_rejections",
    "announce_stops",
    "announce_suggestions",
    "announce_watch",
    "announce_watches",
    "tell",
]
