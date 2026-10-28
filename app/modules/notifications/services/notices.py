"""Single notices about one event: a friend joined, a payout, a feedback answer.

Each has a ``queue_*`` that sends the task after the commit, and the
``announce_*`` the task runs.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.common.hooks import on
from app.common.i18n import override
from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import NoticeKind
from app.modules.notifications.exceptions import NotLinked
from app.modules.notifications.models import InboxSeen, TelegramChat
from app.modules.notifications.selectors import chat_for
from app.modules.notifications.services.compose import (
    feedback_message,
    miniapp_button,
    withdrawal_message,
)
from app.modules.notifications.services.compose_referral import (
    invitee_name,
    referral_message,
)
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.send import send_to

logger = logging.getLogger(__name__)
EDITABLE: frozenset[str] = frozenset(
    {
        "notify_suggestions",
        "notify_report",
        "notify_rejections",
        "notify_spend_guard",
        "notify_daily_report",
    }
)


def save_preferences(db: Session, *, user: User, **values: bool) -> TelegramChat:
    chat = chat_for(db, owner=user)
    if chat is None:
        raise NotLinked
    for field in sorted(EDITABLE & set(values)):
        setattr(chat, field, bool(values[field]))
    db.flush()
    return chat


def mark_seen(db: Session, *, owner: User, keys: frozenset[str]) -> int:
    db.execute(
        delete(InboxSeen).where(
            InboxSeen.owner_id == owner.id, InboxSeen.key.not_in(keys)
        )
    )
    known = set(db.scalars(select(InboxSeen.key).where(InboxSeen.owner_id == owner.id)))
    fresh = sorted(keys - known)
    if fresh:
        # Two tabs can press the bell together: the later one skips what the
        # earlier one wrote instead of failing on the unique key.
        db.execute(
            insert(InboxSeen)
            .values([{"owner_id": owner.id, "key": key} for key in fresh])
            .on_conflict_do_nothing(index_elements=["owner_id", "key"])
        )
    return len(fresh)


def _deliver(
    db: Session,
    *,
    owner: User,
    kind: str,
    subject: str,
    text_of: Any,
    now: datetime,
    buttons_of: Any = None,
) -> bool:
    chat = chat_for(db, owner=owner)
    if chat is None or not is_configured():
        return False
    with override(owner.language):
        notice = claim(db, chat=chat, kind=kind, subject=subject)
        if notice is None:
            return False
        text = text_of()
        buttons = buttons_of() if buttons_of else ()
        with bot() as client:
            sent = send_to(
                db, client=client, chat=chat, text=text, buttons=buttons, now=now
            )
    stamp(db, notice=notice, message_id=sent, now=now)
    return bool(sent)


# -- payouts ------------------------------------------------------------------------


def queue_withdrawal_notice(
    db: Session,
    *,
    owner: User,
    withdrawal_id: str,
    outcome: str,
    amount_minor: int,
    currency: str,
    card_last4: str,
    reason: str,
) -> None:
    from app.modules.notifications.tasks import deliver_withdrawal_notice_task

    args = (
        str(owner.id),
        withdrawal_id,
        outcome,
        amount_minor,
        currency,
        card_last4,
        reason,
    )
    on_commit(db, lambda: deliver_withdrawal_notice_task.delay(*args))


def announce_withdrawal(
    db: Session,
    *,
    owner: User,
    withdrawal_id: str,
    outcome: str,
    amount_minor: int,
    currency: str,
    card_last4: str,
    reason: str,
    now: datetime,
) -> bool:
    sent = _deliver(
        db,
        owner=owner,
        kind=NoticeKind.WITHDRAWAL,
        subject=f"{withdrawal_id}:{outcome}",
        text_of=lambda: (
            withdrawal_message(
                outcome=outcome,
                amount=format_minor(amount_minor=amount_minor, currency=currency),
                card_last4=card_last4,
                reason=reason,
            ).text
        ),
        now=now,
    )
    logger.info(
        "withdrawal answer announced", extra={"owner_id": str(owner.id), "sent": sent}
    )
    return sent


# -- feedback -----------------------------------------------------------------------


def queue_feedback_notice(
    db: Session,
    *,
    owner: User,
    feedback_id: str,
    outcome: str,
    kind: str,
    amount_minor: int,
    currency: str,
    reason: str,
) -> None:
    from app.modules.notifications.tasks import deliver_feedback_notice_task

    args = (str(owner.id), feedback_id, outcome, kind, amount_minor, currency, reason)
    on_commit(db, lambda: deliver_feedback_notice_task.delay(*args))


def announce_feedback(
    db: Session,
    *,
    owner: User,
    feedback_id: str,
    outcome: str,
    kind: str,
    amount_minor: int,
    currency: str,
    reason: str,
    now: datetime,
) -> bool:
    def text() -> str:
        amount = (
            format_minor(amount_minor=amount_minor, currency=currency)
            if currency
            else ""
        )
        return feedback_message(
            outcome=outcome, kind=kind, amount=amount, reason=reason
        ).text

    sent = _deliver(
        db,
        owner=owner,
        kind=NoticeKind.FEEDBACK,
        subject=f"{feedback_id}:{outcome}",
        text_of=text,
        now=now,
    )
    logger.info(
        "feedback answer announced", extra={"owner_id": str(owner.id), "sent": sent}
    )
    return sent


# -- a friend joined ----------------------------------------------------------------


@on("referrals.bound")
def queue_referral_notice(
    *, db: Session, referrer: User, invited: User, **_: Any
) -> None:
    from app.modules.notifications.tasks import deliver_referral_notice_task

    referrer_id, invited_id = str(referrer.id), str(invited.id)

    def send() -> None:
        try:
            deliver_referral_notice_task.delay(referrer_id, invited_id)
        except Exception:
            logger.warning("referral notice not queued", exc_info=True)

    on_commit(db, send)


def announce_referral(
    db: Session, *, referrer: User, invited: User, now: datetime
) -> bool:
    from app.modules.referrals.selectors import inviter_of, plan_rewards

    inviter = inviter_of(db, owner=invited)
    if inviter is None or inviter.id != referrer.id:
        return False
    if chat_for(db, owner=referrer) is None or not is_configured():
        logger.info("referral notice skipped", extra={"owner_id": str(referrer.id)})
        return False
    invited_chat = chat_for(db, owner=invited)
    username = invited_chat.username if invited_chat is not None else ""
    sent = _deliver(
        db,
        owner=referrer,
        kind=NoticeKind.REFERRAL,
        subject=str(invited.id),
        text_of=lambda: (
            referral_message(
                name=invitee_name(invited=invited, username=username),
                rewards=tuple(
                    (
                        row.name,
                        format_minor(
                            amount_minor=row.bonus_minor, currency=row.currency
                        ),
                    )
                    for row in plan_rewards(db)
                ),
            ).text
        ),
        buttons_of=lambda: miniapp_button(
            route="referrals:wallet", label="Daromadni ochish"
        ),
        now=now,
    )
    logger.info(
        "referral announced", extra={"owner_id": str(referrer.id), "sent": sent}
    )
    return sent


def user_of(db: Session, owner_id: str) -> User | None:
    try:
        return db.get(User, uuid.UUID(owner_id))
    except ValueError:
        return None


__all__ = [
    "EDITABLE",
    "announce_feedback",
    "announce_referral",
    "announce_withdrawal",
    "mark_seen",
    "queue_feedback_notice",
    "queue_referral_notice",
    "queue_withdrawal_notice",
    "save_preferences",
    "user_of",
]
