"""The waiting list's lines about the cabinet itself, said on every page.

The connection, the entitlement, unfinished preparation, the office's chat
reply and its answer to a piece of feedback.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.ads.models import Campaign, LapseHold
from app.modules.ads.selectors.lapse import cut_off_due, open_hold
from app.modules.audit.constants import ActionStatus, ActionType
from app.modules.audit.models import ActionLog
from app.modules.billing.constants import EXPIRY_REMINDER_DAYS
from app.modules.billing.models import Subscription
from app.modules.billing.selectors.subscription import (
    days_left,
    frozen_subscription,
    has_ever_subscribed,
    subscription_ended_at,
)
from app.modules.integrations.selectors.connection import broken_meta_connection
from app.modules.notifications.selectors import deadline_text
from app.modules.referrals.constants import FeedbackStatus
from app.modules.referrals.selectors import last_answered_feedback
from core.inbox import InboxItem

FEEDBACK_ANSWER_DAYS = 14
# TZ 2.1: how long «the copy is ready» stays in the list.
COPY_READY_DAYS = 2


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


def _copies(db: Session, *, owner: User, now: datetime) -> list[InboxItem]:
    """TZ 2.1: a campaign's copy made in the background is ready."""
    rows = db.scalars(
        select(ActionLog)
        .where(
            ActionLog.owner_id == owner.id,
            ActionLog.action == ActionType.COPY_CAMPAIGN,
            ActionLog.status == ActionStatus.APPLIED,
            ActionLog.applied_at >= now - timedelta(days=COPY_READY_DAYS),
        )
        .order_by(ActionLog.applied_at.desc())
    )
    items = []
    for log in rows:
        source = db.scalar(
            select(Campaign.name).where(
                Campaign.owner_id == owner.id,
                Campaign.provider == log.target_provider,
                Campaign.external_id == log.target_external_id,
            )
        )
        items.append(
            InboxItem(
                key=f"copy:{log.id}",
                kind="copy",
                level="news",
                title=f"Kampaniya nusxasi tayyor: «{source or log.target_external_id} — nusxa»",
                body="Nusxa to'xtatilgan holatda. Tekshirib, o'zingiz yoqasiz.",
                since=log.applied_at,
                action="Kampaniyalarni ochish",
                href=reverse("ads:campaigns"),
            )
        )
    return items


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
    """Access frozen, ending, or ended; just released. One at a time."""
    if live is None:
        frozen = frozen_subscription(db, owner=owner)
        if frozen is not None:
            return [_frozen(db, subscription=frozen)]
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

    released = _released(db, owner=owner, live=live, now=now)
    if released is not None:
        return [released]
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
                "Obuna %(days)d kundan keyin tugaydi. Tugaganidan 24 soat "
                "o'tib platformada yaratilgan reklamalar to'xtatiladi, "
                "72 soatdan keyin yangi lidlar va raqamlar yig'ilmaydi. "
                "To'lov qilsangiz, hammasi qayta ishlaydi."
            )
            % {"days": left},
            since=live.expires_at,
            action="Yangilash",
            href=reverse("billing:plans"),
        )
    ]


def _lapse(db: Session, *, hold: LapseHold, now: datetime) -> InboxItem:
    """The ended subscription's adverts: stopped, never deleted; a payment
    brings them back. 72 hours on, sync and leads stop too."""
    if cut_off_due(hold=hold, now=now):
        return InboxItem(
            key=f"subscription:lapse:{hold.id}:cut_off",
            kind="subscription",
            level="urgent",
            title="Obuna yangilanmadi",
            body=(
                "Reklamalaringiz to'xtatilgan holda saqlanadi, yangi lidlar "
                "va raqamlar yig'ilmaydi. To'lov qilib obunani davom "
                "ettirishingiz mumkin - reklamalar o'zi qayta yoqiladi."
            ),
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
            "Platformada yaratilgan reklamalaringiz to'xtatildi. To'lov qilib "
            "obunani davom ettirishingiz mumkin - reklamalar o'zi qayta yoqiladi."
        ),
        since=hold.started_at,
        action="Obunani yangilash",
        href=reverse("billing:plans"),
    )


def _frozen(db: Session, *, subscription: Subscription) -> InboxItem:
    """The office froze the subscription: why, and until when."""
    until = (
        deadline_text(db, owner=subscription.owner, moment=subscription.frozen_until)
        if subscription.frozen_until is not None
        else ""
    )
    lines = ["Obuna kunlari sarflanmaydi, reklamalar to'xtatilgan."]
    if subscription.frozen_reason:
        lines.insert(0, f"Sabab: {subscription.frozen_reason}.")
    if until:
        lines.append(f"Muzlatish {until} da tugaydi.")
    return InboxItem(
        key=f"subscription:frozen:{subscription.id}:{subscription.frozen_at:%Y%m%d%H%M}",
        kind="subscription",
        level="urgent",
        title="Obuna muzlatilgan",
        body=" ".join(lines),
        since=subscription.frozen_at,
        action="",
        href="",
    )


# The release is shown this long in the cabinet after it.
RELEASE_SHOWN_FOR = timedelta(days=3)


def _released(
    db: Session, *, owner: User, live: Subscription, now: datetime
) -> InboxItem | None:
    from app.modules.billing.services.freeze import last_release

    change = last_release(db, owner=owner, since=now - RELEASE_SHOWN_FOR)
    if change is None or change.subscription_id != live.id:
        return None
    until = deadline_text(db, owner=owner, moment=live.expires_at)
    return InboxItem(
        key=f"subscription:unfrozen:{change.id}",
        kind="subscription",
        level="news",
        title="Obuna muzlatishdan chiqdi",
        body=(
            "Obunangiz yana ishlayapti. Muzlatilgan kunlar sarflanmadi: obuna "
            "%(until)s gacha amal qiladi."
        )
        % {"until": until},
        since=change.occurred_at,
        action="Obunani ko'rish",
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
        *_copies(db, owner=owner, now=now),
    ]


__all__ = ["COPY_READY_DAYS", "FEEDBACK_ANSWER_DAYS", "cabinet_items"]
