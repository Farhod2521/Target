"""Hamyon: rewards in, holds against bills, payouts out, feedback paid for."""

import logging
import secrets
from datetime import datetime
from pathlib import PurePath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import storage
from app.common.config import settings
from app.common.crypto import encrypt
from app.common.exceptions import ConfigurationError
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.exceptions import ReasonRequired
from app.modules.billing.models import Invoice
from app.modules.referrals.constants import (
    CARD_DIGITS,
    CARD_HOLDER_MAX,
    CODE_ALPHABET,
    CODE_ATTEMPTS,
    CODE_LENGTH,
    FEEDBACK_EXTENSIONS,
    FEEDBACK_KIND_LABELS,
    FEEDBACK_MAX_BYTES,
    FEEDBACK_TEXT_MAX,
    FEEDBACK_TEXT_MIN,
    FEEDBACK_UPLOAD_DIR,
    REFERRAL_PERCENT,
    FeedbackKind,
    FeedbackPromptAnswer,
    FeedbackStatus,
    PayoutMethod,
    PayoutStatus,
    ReferralMode,
    RewardStatus,
)
from app.modules.referrals.exceptions import (
    AccessReasonRequired,
    CardHolderRequired,
    CardNumberInvalid,
    EarnerNotActive,
    FeedbackAlreadyDecided,
    FeedbackAlreadyPaid,
    FeedbackAlreadySent,
    FeedbackClosed,
    FeedbackConsentRequired,
    FeedbackFileInvalid,
    FeedbackNoPlan,
    FeedbackTextTooShort,
    InsufficientBalance,
    PayoutAlreadyVoided,
    PayoutNotPaid,
    ReferrerNotEligible,
    WithdrawalAlreadyDecided,
    WithdrawalLocked,
    WithdrawalPending,
    WithdrawalsClosed,
)
from app.modules.referrals.models import (
    Feedback,
    FeedbackPrompt,
    ReferralAccess,
    ReferralBinding,
    ReferralCode,
    ReferralReward,
    WalletSpend,
    WithdrawalRequest,
)
from app.modules.referrals.selectors import (
    available_minor,
    feedback_offer,
    may_invite,
    may_withdraw,
    open_withdrawal,
    spendable_minor,
)

logger = logging.getLogger(__name__)


def _lock_user(db: Session, user_id: object) -> User | None:
    return db.get(User, user_id, with_for_update=True)


def accrue_reward(
    db: Session, *, invoice: Invoice, now: datetime
) -> ReferralReward | None:
    from app.modules.billing.selectors import paid_before

    if invoice.owner_id is None:
        return None
    binding = db.scalar(
        select(ReferralBinding).where(ReferralBinding.owner_id == invoice.owner_id)
    )
    if binding is None:
        return None
    if binding.referrer_id is None:
        logger.info(
            "referral reward skipped: inviter gone", extra={"invoice": invoice.number}
        )
        return None
    existing = db.scalar(
        select(ReferralReward).where(ReferralReward.binding_id == binding.id)
    )
    if existing is not None:
        return existing
    if paid_before(db, invoice=invoice):
        return None
    if not may_invite(db, owner_id=binding.referrer_id):
        return None
    amount = invoice.amount_minor * REFERRAL_PERCENT // 100
    if amount <= 0:
        return None
    reward = ReferralReward(
        owner_id=binding.referrer_id,
        binding_id=binding.id,
        invoice_id=invoice.id,
        base_minor=invoice.amount_minor,
        currency=invoice.currency,
        percent=REFERRAL_PERCENT,
        amount_minor=amount,
        status=RewardStatus.EARNED,
        earned_at=now,
    )
    try:
        with db.begin_nested():
            db.add(reward)
    except IntegrityError:
        return db.scalar(
            select(ReferralReward).where(ReferralReward.binding_id == binding.id)
        )
    emit(
        db,
        owner_id=reward.owner_id,
        name=EventName.REFERRAL_REWARDED,
        aggregate_type="reward",
        aggregate_id=reward.id,
        payload={
            "binding_id": str(binding.id),
            "invoice": invoice.number,
            "base_minor": reward.base_minor,
            "currency": reward.currency,
            "percent": reward.percent,
            "amount_minor": reward.amount_minor,
        },
        occurred_at=now,
    )
    return reward


def hold_wallet(
    db: Session, *, invoice: Invoice, amount_minor: int, now: datetime
) -> int:
    owner = _lock_user(db, invoice.owner_id)
    if owner is None:
        return 0
    existing = db.scalar(
        select(WalletSpend).where(
            WalletSpend.owner_id == owner.id, WalletSpend.invoice_id == invoice.id
        )
    )
    held = existing.amount_minor if existing is not None else 0
    room = spendable_minor(
        db, owner=owner, currency=invoice.currency, reclaim_minor=held
    )
    amount = max(0, min(amount_minor, room))
    if amount == held:
        return amount
    if amount == 0 and existing is not None:
        db.delete(existing)
    elif existing is not None:
        existing.amount_minor = amount
    else:
        db.add(
            WalletSpend(
                owner_id=owner.id,
                invoice_id=invoice.id,
                amount_minor=amount,
                currency=invoice.currency,
            )
        )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.WALLET_APPLIED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "number": invoice.number,
            "amount_minor": amount,
            "previous_minor": held,
            "currency": invoice.currency,
        },
        occurred_at=now,
    )
    db.flush()
    return amount


def ensure_referral_code(db: Session, *, owner: User) -> ReferralCode:
    if not may_invite(db, owner_id=owner.id):
        raise ReferrerNotEligible
    existing = db.scalar(select(ReferralCode).where(ReferralCode.owner_id == owner.id))
    if existing is not None:
        return existing
    for _attempt in range(CODE_ATTEMPTS):
        row = ReferralCode(
            owner_id=owner.id,
            code="".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH)),
        )
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:
            found = db.scalar(
                select(ReferralCode).where(ReferralCode.owner_id == owner.id)
            )
            if found is not None:
                return found
            continue
        emit(
            db,
            owner_id=owner.id,
            name=EventName.REFERRAL_CODE_ISSUED,
            aggregate_type="referral_code",
            aggregate_id=row.id,
            payload={"code": row.code},
            occurred_at=row.created_at,
        )
        return row
    raise ConfigurationError("referral code generator produced only collisions")


def set_referral_access(
    db: Session,
    *,
    owner: User,
    mode: ReferralMode,
    actor: User,
    reason: str,
    now: datetime,
) -> ReferralAccess:
    if not reason.strip():
        raise AccessReasonRequired
    access = db.scalar(
        select(ReferralAccess)
        .where(ReferralAccess.owner_id == owner.id)
        .with_for_update()
    )
    if access is None:
        access = ReferralAccess(owner_id=owner.id, mode=ReferralMode.AUTO, reason="")
        db.add(access)
    previous = access.mode
    access.mode = mode
    access.set_by_id = actor.id
    access.reason = reason.strip()
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.REFERRAL_ACCESS_CHANGED,
        aggregate_type="referral_access",
        aggregate_id=access.id,
        payload={
            "from": previous,
            "to": str(mode),
            "reason": reason.strip(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return access


def request_withdrawal(
    db: Session,
    *,
    owner: User,
    amount_minor: int,
    currency: str,
    card_number: str,
    card_holder: str,
    now: datetime,
) -> WithdrawalRequest:
    digits = card_number.replace(" ", "").replace("-", "")
    holder = " ".join(card_holder.split())
    if len(digits) != CARD_DIGITS or not (digits.isascii() and digits.isdigit()):
        raise CardNumberInvalid
    if not holder or len(holder) > CARD_HOLDER_MAX:
        raise CardHolderRequired
    locked = _lock_user(db, owner.id)
    if locked is None:
        raise InsufficientBalance
    if not settings.withdrawals_open:
        raise WithdrawalsClosed
    if not may_withdraw(db, owner=locked):
        raise WithdrawalLocked
    if open_withdrawal(db, owner=locked) is not None:
        raise WithdrawalPending
    if amount_minor <= 0 or amount_minor > available_minor(
        db, owner=locked, currency=currency
    ):
        raise InsufficientBalance
    ask = WithdrawalRequest(
        owner_id=locked.id,
        amount_minor=amount_minor,
        currency=currency,
        method=PayoutMethod.CARD,
        status=PayoutStatus.REQUESTED,
        card_number_encrypted=encrypt(digits),
        card_last4=digits[-4:],
        card_holder=holder,
        pay_reference="",
        note="",
        reject_reason="",
        void_reason="",
    )
    try:
        with db.begin_nested():
            db.add(ask)
    except IntegrityError as exc:
        raise WithdrawalPending from exc
    emit(
        db,
        owner_id=locked.id,
        name=EventName.WITHDRAWAL_REQUESTED,
        aggregate_type="withdrawal",
        aggregate_id=ask.id,
        payload={
            "amount_minor": ask.amount_minor,
            "currency": ask.currency,
            "card_last4": ask.card_last4,
        },
        occurred_at=now,
    )
    return ask


def _open_ask(db: Session, *, ask: WithdrawalRequest) -> WithdrawalRequest:
    locked = db.get(WithdrawalRequest, ask.id, with_for_update=True)
    if locked is None or locked.status != PayoutStatus.REQUESTED:
        raise WithdrawalAlreadyDecided
    return locked


def _announce_ask(
    db: Session, *, ask: WithdrawalRequest, name: EventName, actor: User, now: datetime
) -> None:
    from app.modules.notifications.services import queue_withdrawal_notice

    emit(
        db,
        owner_id=ask.owner_id,
        name=name,
        aggregate_type="withdrawal",
        aggregate_id=ask.id,
        payload={
            "amount_minor": ask.amount_minor,
            "currency": ask.currency,
            "card_last4": ask.card_last4,
            "pay_reference": ask.pay_reference,
            "reason": ask.reject_reason,
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    queue_withdrawal_notice(
        db,
        owner=ask.owner,
        withdrawal_id=str(ask.id),
        outcome=str(ask.status),
        amount_minor=ask.amount_minor,
        currency=ask.currency,
        card_last4=ask.card_last4,
        reason=ask.reject_reason,
    )


def pay_withdrawal(
    db: Session,
    *,
    ask: WithdrawalRequest,
    pay_reference: str,
    actor: User,
    now: datetime,
) -> WithdrawalRequest:
    _lock_user(db, ask.owner_id)
    locked = _open_ask(db, ask=ask)
    if available_minor(db, owner=locked.owner, currency=locked.currency) < 0:
        raise InsufficientBalance
    locked.status = PayoutStatus.PAID
    locked.pay_reference = pay_reference.strip()
    locked.decided_by_id = actor.id
    locked.decided_at = now
    db.flush()
    _announce_ask(db, ask=locked, name=EventName.WITHDRAWAL_PAID, actor=actor, now=now)
    return locked


def reject_withdrawal(
    db: Session, *, ask: WithdrawalRequest, reason: str, actor: User, now: datetime
) -> WithdrawalRequest:
    if not reason.strip():
        raise ReasonRequired
    locked = _open_ask(db, ask=ask)
    locked.status = PayoutStatus.REJECTED
    locked.reject_reason = reason.strip()
    locked.decided_by_id = actor.id
    locked.decided_at = now
    db.flush()
    _announce_ask(
        db, ask=locked, name=EventName.WITHDRAWAL_REJECTED, actor=actor, now=now
    )
    return locked


def record_payout(
    db: Session,
    *,
    owner: User,
    amount_minor: int,
    currency: str,
    method: PayoutMethod,
    pay_reference: str,
    actor: User,
    reason: str,
    now: datetime,
) -> WithdrawalRequest:
    if not reason.strip():
        raise ReasonRequired
    locked = _lock_user(db, owner.id)
    if locked is None:
        raise InsufficientBalance
    if not may_withdraw(db, owner=locked):
        raise EarnerNotActive
    if amount_minor <= 0 or amount_minor > available_minor(
        db, owner=locked, currency=currency
    ):
        raise InsufficientBalance
    payout = WithdrawalRequest(
        owner_id=locked.id,
        amount_minor=amount_minor,
        currency=currency,
        method=method,
        pay_reference=pay_reference.strip(),
        status=PayoutStatus.PAID,
        decided_by_id=actor.id,
        decided_at=now,
        note=reason.strip(),
        card_last4="",
        card_holder="",
        reject_reason="",
        void_reason="",
    )
    db.add(payout)
    db.flush()
    emit(
        db,
        owner_id=locked.id,
        name=EventName.WITHDRAWAL_PAID,
        aggregate_type="withdrawal",
        aggregate_id=payout.id,
        payload={
            "amount_minor": payout.amount_minor,
            "currency": payout.currency,
            "method": str(payout.method),
            "pay_reference": payout.pay_reference,
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return payout


def void_payout(
    db: Session, *, payout: WithdrawalRequest, actor: User, reason: str, now: datetime
) -> WithdrawalRequest:
    if not reason.strip():
        raise ReasonRequired
    locked = db.get(WithdrawalRequest, payout.id, with_for_update=True)
    if locked is None or locked.status == PayoutStatus.VOIDED:
        raise PayoutAlreadyVoided
    if locked.status != PayoutStatus.PAID:
        raise PayoutNotPaid
    locked.status = PayoutStatus.VOIDED
    locked.void_reason = reason.strip()
    locked.voided_at = now
    locked.voided_by_id = actor.id
    emit(
        db,
        owner_id=locked.owner_id,
        name=EventName.WITHDRAWAL_VOIDED,
        aggregate_type="withdrawal",
        aggregate_id=locked.id,
        payload={
            "amount_minor": locked.amount_minor,
            "currency": locked.currency,
            "reason": reason.strip(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    db.flush()
    return locked


def answer_feedback_prompt(
    db: Session, *, owner: User, answer: FeedbackPromptAnswer, now: datetime
) -> FeedbackPrompt:
    prompt = db.scalar(
        select(FeedbackPrompt).where(FeedbackPrompt.owner_id == owner.id)
    )
    if prompt is not None:
        return prompt
    prompt = FeedbackPrompt(owner_id=owner.id, answer=answer)
    db.add(prompt)
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.FEEDBACK_PROMPT_ANSWERED,
        aggregate_type="feedback_prompt",
        aggregate_id=prompt.id,
        payload={"answer": str(answer)},
        occurred_at=now,
    )
    return prompt


def submit_feedback(
    db: Session,
    *,
    owner: User,
    kind: FeedbackKind,
    text: str,
    upload: BinaryIO | None,
    upload_name: str,
    upload_size: int,
    consent: bool,
    now: datetime,
) -> Feedback:
    locked = _lock_user(db, owner.id)
    if locked is None or not feedback_offer(db, owner=locked).is_open:
        raise FeedbackClosed
    if not consent:
        raise FeedbackConsentRequired
    if db.scalar(
        select(Feedback.id)
        .where(
            Feedback.owner_id == locked.id, Feedback.status != FeedbackStatus.REJECTED
        )
        .limit(1)
    ):
        raise FeedbackAlreadySent
    body = ""
    stored = ""
    if kind == FeedbackKind.TEXT:
        body = text.strip()
        if len(body) < FEEDBACK_TEXT_MIN:
            raise FeedbackTextTooShort(FEEDBACK_TEXT_MIN)
        body = body[:FEEDBACK_TEXT_MAX]
    else:
        suffix = PurePath(upload_name or "").suffix.lower().lstrip(".")
        if (
            upload is None
            or not upload_size
            or suffix not in FEEDBACK_EXTENSIONS[kind]
            or upload_size > FEEDBACK_MAX_BYTES[kind]
        ):
            raise FeedbackFileInvalid
        stored = storage.save(
            upload, folder=f"{FEEDBACK_UPLOAD_DIR}/{locked.id}", filename=upload_name
        )
    piece = Feedback(
        owner_id=locked.id,
        kind=kind,
        status=FeedbackStatus.PENDING,
        text=body,
        file=stored,
        consented_at=now,
        reason="",
        percent=0,
        amount_minor=0,
        currency="",
    )
    try:
        with db.begin_nested():
            db.add(piece)
    except IntegrityError as exc:
        storage.delete(stored)
        raise FeedbackAlreadySent from exc
    emit(
        db,
        owner_id=locked.id,
        name=EventName.FEEDBACK_SUBMITTED,
        aggregate_type="feedback",
        aggregate_id=piece.id,
        payload={"kind": str(kind)},
        occurred_at=now,
    )
    return piece


def _open_feedback(db: Session, *, piece: Feedback) -> Feedback:
    locked = db.get(Feedback, piece.id, with_for_update=True)
    if locked is None or locked.status != FeedbackStatus.PENDING:
        raise FeedbackAlreadyDecided
    return locked


def _announce_feedback(
    db: Session, *, piece: Feedback, name: EventName, actor: User, now: datetime
) -> None:
    from app.modules.notifications.services import queue_feedback_notice

    emit(
        db,
        owner_id=piece.owner_id,
        name=name,
        aggregate_type="feedback",
        aggregate_id=piece.id,
        payload={
            "kind": piece.kind,
            "percent": piece.percent,
            "amount_minor": piece.amount_minor,
            "currency": piece.currency,
            "reason": piece.reason,
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    queue_feedback_notice(
        db,
        owner=piece.owner,
        feedback_id=str(piece.id),
        outcome=str(piece.status),
        kind=str(FEEDBACK_KIND_LABELS.get(piece.kind, piece.kind)),
        amount_minor=piece.amount_minor,
        currency=piece.currency,
        reason=piece.reason,
    )


def approve_feedback(
    db: Session, *, piece: Feedback, actor: User, now: datetime
) -> Feedback:
    _lock_user(db, piece.owner_id)
    locked = _open_feedback(db, piece=piece)
    offer = feedback_offer(db, owner=locked.owner)
    if not offer.is_open:
        raise FeedbackNoPlan
    if offer.is_done:
        raise FeedbackAlreadyPaid
    reward = next(row for row in offer.rewards if row.kind == locked.kind)
    locked.status = FeedbackStatus.APPROVED
    locked.percent = reward.percent
    locked.amount_minor = reward.amount_minor
    locked.currency = offer.currency
    locked.decided_by_id = actor.id
    locked.decided_at = now
    db.flush()
    _announce_feedback(
        db, piece=locked, name=EventName.FEEDBACK_APPROVED, actor=actor, now=now
    )
    return locked


def reject_feedback(
    db: Session, *, piece: Feedback, reason: str, actor: User, now: datetime
) -> Feedback:
    if not reason.strip():
        raise ReasonRequired
    locked = _open_feedback(db, piece=piece)
    locked.status = FeedbackStatus.REJECTED
    locked.reason = reason.strip()
    locked.decided_by_id = actor.id
    locked.decided_at = now
    db.flush()
    _announce_feedback(
        db, piece=locked, name=EventName.FEEDBACK_REJECTED, actor=actor, now=now
    )
    return locked
