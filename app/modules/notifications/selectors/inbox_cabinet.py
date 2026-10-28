"""The waiting list's lines about the cabinet itself, said on every page.

The connection, the entitlement, unfinished preparation, the office's chat
reply and its answer to a piece of feedback.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.models import LapseHold
from app.modules.ads.selectors.lapse import last_warning_due, open_hold
from app.modules.billing.constants import EXPIRY_REMINDER_DAYS
from app.modules.billing.models import Subscription
from app.modules.billing.selectors.subscription import (
    days_left,
    has_ever_subscribed,
    subscription_ended_at,
)
from app.modules.integrations.selectors.connection import broken_meta_connection
from app.modules.notifications.selectors import deadline_text
from app.modules.referrals.constants import FeedbackStatus
from app.modules.referrals.selectors import last_answered_feedback
from core.inbox import InboxItem

FEEDBACK_ANSWER_DAYS = 14


def _feedback(db: Session, *, owner: User, now: datetime) -> list[InboxItem]:
    """The office answered a piece of feedback this customer sent."""
    piece = last_answered_feedback(
        db, owner=owner, since=now - timedelta(days=FEEDBACK_ANSWER_DAYS)
    )
    if piece is None or piece.decided_at is None:
        return []
    approved = piece.status == FeedbackStatus.APPROVED
    return [
        InboxItem(
            key=f"feedback:{piece.id}:{piece.status}",
            kind="feedback",
            level="news",
            title="Fikringiz tasdiqlandi" if approved else "Fikringiz rad etildi",
            body="",
            since=piece.decided_at,
            action="Ko'rish",
            href=f"{reverse('referrals:wallet')}?yol=fikr",
        )
    ]


def _connection(db: Session, *, owner: User) -> list[InboxItem]:
    """The Facebook token that stopped being accepted."""
    connection = broken_meta_connection(db, owner=owner)
    if connection is None:
        return []
    return [
        InboxItem(
            key=f"connection:{connection.id}:{connection.status}",
            kind="connection",
            level="urgent",
            title="Facebook ulanishi uzildi",
            body="Yangi mijozlar kelmayapti va raqamlar yangilanmayapti.",
            since=connection.updated_at,
            action="Qayta ulash",
            href=reverse("integrations:connections"),
        )
    ]


def _subscription(
    db: Session, *, owner: User, live: Subscription | None, now: datetime
) -> list[InboxItem]:
    """Access ending, or ended. Two items and never both."""
    if live is None:
        if not has_ever_subscribed(db, owner=owner):
            return [
                InboxItem(
                    key="subscription:none",
                    kind="subscription",
                    level="urgent",
                    title="Tarif hali ochilmagan",
                    body=(
                        "Reklama berish uchun tarifni oching - "
                        "taklif havolangiz esa hozir ham ishlaydi."
                    ),
                    since=None,
                    action="Tarifni ochish",
                    href=reverse("billing:plans"),
                )
            ]
        hold = open_hold(db, owner=owner)
        if hold is not None:
            return [_lapse(db, hold=hold, now=now)]
        return [
            InboxItem(
                key="subscription:ended",
                kind="subscription",
                level="urgent",
                title="Obuna muddati tugagan",
                body=(
                    "Ma'lumotlar va yarim tayyor reklama joyida - "
                    "faqat o'zgartirish to'xtatilgan."
                ),
                since=subscription_ended_at(db, owner=owner),
                action="Obunani yangilash",
                href=reverse("billing:plans"),
            )
        ]

    left = days_left(subscription=live, now=now)
    if left is None or left > max(EXPIRY_REMINDER_DAYS):
        return []
    return [
        InboxItem(
            key=f"subscription:{live.expires_at:%Y-%m-%d}:{left}",
            kind="subscription",
            level="decision",
            title="Obuna muddati tugayapti",
            body=(
                "%(days)d kundan keyin platformada yaratilgan reklamalar "
                "to'xtatiladi, yana 3 kunda to'lanmasa o'chiriladi."
            )
            % {"days": left},
            since=live.expires_at,
            action="Yangilash",
            href=reverse("billing:plans"),
        )
    ]


def _lapse(db: Session, *, hold: LapseHold, now: datetime) -> InboxItem:
    """The ended subscription's adverts: stopped, and when they go."""
    until = deadline_text(db, owner=hold.owner, moment=hold.delete_after)
    if last_warning_due(hold=hold, now=now):
        return InboxItem(
            key=f"subscription:lapse:{hold.id}:last",
            kind="subscription",
            level="urgent",
            title="Ertaga reklamalaringiz o'chiriladi",
            body=(
                "Obuna yangilanmagani uchun platformada yaratilgan reklamalar "
                "%(until)s da butunlay o'chiriladi. To'lasangiz, ular qayta "
                "yoqiladi."
            )
            % {"until": until},
            since=hold.started_at,
            action="Obunani yangilash",
            href=reverse("billing:plans"),
        )
    return InboxItem(
        key=f"subscription:lapse:{hold.id}",
        kind="subscription",
        level="urgent",
        title="Obuna muddati tugagan",
        body=(
            "Platformada yaratilgan reklamalaringiz to'xtatildi. %(until)s "
            "gacha to'lasangiz, o'zi qayta yoqiladi, aks holda butunlay "
            "o'chiriladi."
        )
        % {"until": until},
        since=hold.started_at,
        action="Obunani yangilash",
        href=reverse("billing:plans"),
    )


def _setup(db: Session, *, owner: User, live: Subscription | None) -> list[InboxItem]:
    """Preparation started and not finished, only for an account that may finish it."""
    from app.modules.onboarding.selectors import setup_overview

    if live is None or live.setup_completed_at is not None:
        return []
    setup = setup_overview(db, owner=owner)
    if setup.ready:
        return []
    return [
        InboxItem(
            key=f"setup:{setup.done}/{setup.total}",
            kind="setup",
            level="decision",
            title="Sozlash tugallanmagan",
            body=f"{setup.done} qadam {setup.total} dan bajarildi.",
            action="Davom ettirish",
            href=reverse("onboarding:start"),
        )
    ]


def _support(db: Session, *, owner: User) -> list[InboxItem]:
    """The office replied and this reader has not opened their chat since."""
    from app.modules.supportchat.selectors import unread_reply

    chat = unread_reply(db, owner=owner)
    if chat is None or chat.last_office_at is None:
        return []
    return [
        InboxItem(
            key=f"support:{chat.id}:{chat.last_office_at:%Y%m%d%H%M%S}",
            kind="support",
            level="news",
            title="Yordam xizmati javob berdi",
            body="",
            since=chat.last_office_at,
            action="Javobni ko'rish",
            href=reverse("supportchat:chat"),
        )
    ]


def cabinet_items(
    db: Session, *, owner: User, live: Subscription | None, now: datetime
) -> list[InboxItem]:
    """The cabinet's own lines, in the order the list itself would sort them."""
    return [
        *_connection(db, owner=owner),
        *_subscription(db, owner=owner, live=live, now=now),
        *_setup(db, owner=owner, live=live),
        *_support(db, owner=owner),
        *_feedback(db, owner=owner, now=now),
    ]


__all__ = ["FEEDBACK_ANSWER_DAYS", "cabinet_items"]
