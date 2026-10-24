import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.money import to_minor
from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.models import Invoice, Plan
from app.modules.referrals.constants import (
    FEEDBACK_KIND_LABELS,
    FEEDBACK_PERCENT,
    FEEDBACK_PROMPT_AFTER_DAYS,
    REFERRAL_PERCENT,
    FeedbackKind,
    FeedbackStatus,
    PayoutStatus,
    ReferralMode,
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
from app.modules.referrals.selectors.eligibility import (
    code_owner,
    may_invite,
    referral_mode,
)

SPENDING_INVOICE_STATUSES = (
    InvoiceStatus.PENDING,
    InvoiceStatus.HELD,
    InvoiceStatus.PAID,
)
LATEST_WINDOW = 30
TELEGRAM_SHARE = "https://t.me/share/url?"


def may_withdraw(db: Session, *, owner: User) -> bool:
    from app.modules.backoffice.constants import SALES_ROLES
    from app.modules.backoffice.permissions import has_role
    from app.modules.billing.constants import SubscriptionStatus
    from app.modules.billing.selectors import live_subscription, paid_invoice_count

    mode = referral_mode(db, owner_id=owner.id)
    if mode != ReferralMode.AUTO:
        return mode == ReferralMode.OPEN
    if has_role(db, owner, SALES_ROLES):
        return True
    subscription = live_subscription(db, owner=owner)
    if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
        return False
    return paid_invoice_count(db, owner=owner) >= 1


def access_of(db: Session, *, owner: User) -> ReferralAccess | None:
    return db.scalar(select(ReferralAccess).where(ReferralAccess.owner_id == owner.id))


def code_of(db: Session, *, owner: User) -> ReferralCode | None:
    return db.scalar(select(ReferralCode).where(ReferralCode.owner_id == owner.id))


@dataclass(frozen=True, slots=True)
class WalletBalance:
    currency: str
    earned_minor: int
    paid_minor: int
    spent_minor: int
    available_minor: int
    held_minor: int = 0


def _sums(db: Session, query: Select[Any]) -> dict[str, int]:
    return {currency: int(total or 0) for currency, total in db.execute(query)}


def _by_currency(model: Any, *conditions: Any) -> Select[Any]:
    return (
        select(model.currency, func.sum(model.amount_minor))
        .where(*conditions)
        .group_by(model.currency)
    )


def _spends_where(owner: User) -> tuple[Any, ...]:
    spending = select(Invoice.id).where(Invoice.status.in_(SPENDING_INVOICE_STATUSES))
    return (WalletSpend.owner_id == owner.id, WalletSpend.invoice_id.in_(spending))


def wallet_balance(db: Session, *, owner: User) -> tuple[WalletBalance, ...]:
    from app.modules.sales.models import SalesCommission

    earned = _sums(
        db, _by_currency(ReferralReward, ReferralReward.owner_id == owner.id)
    )
    for currency, total in _sums(
        db, _by_currency(SalesCommission, SalesCommission.owner_id == owner.id)
    ).items():
        earned[currency] = earned.get(currency, 0) + total
    for currency, total in _sums(
        db,
        _by_currency(
            Feedback,
            Feedback.owner_id == owner.id,
            Feedback.status == FeedbackStatus.APPROVED,
        ),
    ).items():
        earned[currency] = earned.get(currency, 0) + total
    paid = _sums(
        db,
        _by_currency(
            WithdrawalRequest,
            WithdrawalRequest.owner_id == owner.id,
            WithdrawalRequest.status == PayoutStatus.PAID,
        ),
    )
    spent = _sums(db, _by_currency(WalletSpend, *_spends_where(owner)))
    held = _sums(
        db,
        _by_currency(
            WithdrawalRequest,
            WithdrawalRequest.owner_id == owner.id,
            WithdrawalRequest.status == PayoutStatus.REQUESTED,
        ),
    )
    return tuple(
        WalletBalance(
            currency=currency,
            earned_minor=earned.get(currency, 0),
            paid_minor=paid.get(currency, 0),
            spent_minor=spent.get(currency, 0),
            held_minor=held.get(currency, 0),
            available_minor=(
                earned.get(currency, 0)
                - paid.get(currency, 0)
                - spent.get(currency, 0)
                - held.get(currency, 0)
            ),
        )
        for currency in sorted(set(earned) | set(paid) | set(spent) | set(held))
    )


def available_minor(db: Session, *, owner: User, currency: str) -> int:
    row = next(
        (row for row in wallet_balance(db, owner=owner) if row.currency == currency),
        None,
    )
    return row.available_minor if row is not None else 0


def spendable_minor(
    db: Session, *, owner: User, currency: str, reclaim_minor: int
) -> int:
    if referral_mode(db, owner_id=owner.id) == ReferralMode.CLOSED:
        return 0
    return max(0, available_minor(db, owner=owner, currency=currency) + reclaim_minor)


def reward_history(db: Session, *, owner: User) -> list[ReferralReward]:
    return list(
        db.scalars(
            select(ReferralReward)
            .where(ReferralReward.owner_id == owner.id)
            .order_by(ReferralReward.earned_at.desc())
        )
    )


def payout_history(db: Session, *, owner: User) -> list[WithdrawalRequest]:
    return list(
        db.scalars(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.owner_id == owner.id)
            .order_by(WithdrawalRequest.created_at.desc())
        )
    )


def spend_history(db: Session, *, owner: User) -> list[WalletSpend]:
    return list(
        db.scalars(
            select(WalletSpend)
            .where(*_spends_where(owner))
            .order_by(WalletSpend.created_at.desc())
        )
    )


def invited_users(db: Session, *, owner: User) -> list[ReferralBinding]:
    return list(
        db.scalars(
            select(ReferralBinding)
            .where(ReferralBinding.referrer_id == owner.id)
            .order_by(ReferralBinding.created_at.desc())
        )
    )


def inviter_of(db: Session, *, owner: User) -> User | None:
    binding = db.scalar(
        select(ReferralBinding).where(ReferralBinding.owner_id == owner.id)
    )
    return binding.referrer if binding is not None else None


def open_withdrawal(db: Session, *, owner: User) -> WithdrawalRequest | None:
    return db.scalar(
        select(WithdrawalRequest)
        .where(
            WithdrawalRequest.owner_id == owner.id,
            WithdrawalRequest.status == PayoutStatus.REQUESTED,
        )
        .limit(1)
    )


@dataclass(frozen=True, slots=True)
class WalletCounts:
    rewards: int
    payouts: int


def wallet_counts(db: Session, *, owner: User) -> WalletCounts:
    rewards = db.scalar(
        select(func.count())
        .select_from(ReferralReward)
        .where(ReferralReward.owner_id == owner.id)
    )
    payouts = db.scalar(
        select(func.count())
        .select_from(WithdrawalRequest)
        .where(
            WithdrawalRequest.owner_id == owner.id,
            WithdrawalRequest.status == PayoutStatus.PAID,
        )
    )
    return WalletCounts(rewards=int(rewards or 0), payouts=int(payouts or 0))


@dataclass(frozen=True, slots=True)
class FeedbackReward:
    kind: str
    label: str
    percent: int
    amount_minor: int
    status: str = ""
    reason: str = ""
    paid_minor: int = 0
    paid_currency: str = ""
    is_shut: bool = False

    @property
    def may_send(self) -> bool:
        return not self.is_shut and self.status in ("", FeedbackStatus.REJECTED)

    @property
    def is_paid(self) -> bool:
        return self.status == FeedbackStatus.APPROVED


@dataclass(frozen=True, slots=True)
class FeedbackOffer:
    is_open: bool
    rewards: tuple[FeedbackReward, ...]
    total_minor: int
    currency: str

    @property
    def total_percent(self) -> int:
        return max(row.percent for row in self.rewards)

    @property
    def earned_percent(self) -> int:
        return sum(row.percent for row in self.rewards if row.is_paid)

    @property
    def earned_minor(self) -> int:
        return sum(row.paid_minor for row in self.rewards)

    @property
    def earned_currency(self) -> str:
        return next((row.paid_currency for row in self.rewards if row.is_paid), "")

    @property
    def is_done(self) -> bool:
        return any(row.is_paid for row in self.rewards)


def feedback_history(db: Session, *, owner: User) -> list[Feedback]:
    return list(
        db.scalars(
            select(Feedback)
            .where(Feedback.owner_id == owner.id)
            .order_by(Feedback.created_at.desc())
        )
    )


def feedback_offer(db: Session, *, owner: User) -> FeedbackOffer:
    from app.modules.billing.selectors import live_subscription

    latest: dict[str, Feedback] = {}
    for row in feedback_history(db, owner=owner)[:LATEST_WINDOW]:
        latest.setdefault(row.kind, row)
    live = {
        kind for kind, row in latest.items() if row.status != FeedbackStatus.REJECTED
    }
    subscription = live_subscription(db, owner=owner)
    plan = subscription.plan if subscription else None
    is_open = not (plan is None or plan.is_one_time or plan.price <= 0)
    price_minor = (
        int(to_minor(amount=str(plan.price), currency=plan.currency))
        if is_open and plan
        else 0
    )
    rewards = []
    for kind, percent in FEEDBACK_PERCENT.items():
        piece = latest.get(kind)
        rewards.append(
            FeedbackReward(
                kind=str(kind),
                label=str(FEEDBACK_KIND_LABELS.get(kind, kind)),
                percent=percent,
                amount_minor=price_minor * percent // 100,
                status=piece.status if piece else "",
                reason=piece.reason if piece else "",
                paid_currency=piece.currency if piece else "",
                paid_minor=piece.amount_minor
                if piece and piece.status == FeedbackStatus.APPROVED
                else 0,
                is_shut=bool(live - {kind}),
            )
        )
    total = max(row.amount_minor for row in rewards)
    return FeedbackOffer(
        is_open, tuple(rewards), total, plan.currency if is_open and plan else ""
    )


def last_answered_feedback(
    db: Session, *, owner: User, since: datetime
) -> Feedback | None:
    return db.scalar(
        select(Feedback)
        .where(
            Feedback.owner_id == owner.id,
            Feedback.decided_at >= since,
            Feedback.status != FeedbackStatus.PENDING,
        )
        .order_by(Feedback.decided_at.desc())
        .limit(1)
    )


def feedback_prompt_due(
    db: Session, *, owner: User, now: datetime
) -> FeedbackOffer | None:
    if owner.date_joined > now - timedelta(days=FEEDBACK_PROMPT_AFTER_DAYS):
        return None
    if db.scalar(select(FeedbackPrompt.id).where(FeedbackPrompt.owner_id == owner.id)):
        return None
    if db.scalar(
        select(Feedback.id)
        .where(
            Feedback.owner_id == owner.id, Feedback.status != FeedbackStatus.REJECTED
        )
        .limit(1)
    ):
        return None
    offer = feedback_offer(db, owner=owner)
    return offer if offer.is_open else None


@dataclass(frozen=True, slots=True)
class PlanReward:
    name: str
    price_minor: int
    bonus_minor: int
    currency: str


def plan_rewards(db: Session, *, friends: int = 1) -> tuple[PlanReward, ...]:
    from app.modules.billing.selectors import sellable_plans

    return tuple(
        _plan_reward(plan=plan, friends=friends) for plan in sellable_plans(db)
    )


def _plan_reward(*, plan: Plan, friends: int) -> PlanReward:
    price_minor = int(to_minor(amount=str(plan.price), currency=plan.currency))
    return PlanReward(
        name=plan.name,
        price_minor=price_minor,
        bonus_minor=price_minor * REFERRAL_PERCENT // 100 * friends,
        currency=plan.currency,
    )


def invite_link(*, code: str) -> str:
    return f"{settings.site_url}/r/{code}/"


def share_url(*, link: str) -> str:
    text = (
        "targetolog.ai — reklamangizni AI boshqaradi. "
        "Shu havola orqali ro'yxatdan o'ting:"
    )
    return TELEGRAM_SHARE + urlencode({"url": link, "text": text})


@dataclass(frozen=True, slots=True)
class InviteOffer:
    link: str
    share_url: str
    top_bonus: PlanReward | None
    percent: int


def invite_offer(db: Session, *, owner: User) -> InviteOffer | None:
    if referral_mode(db, owner_id=owner.id) == ReferralMode.CLOSED:
        return None
    if db.scalar(
        select(ReferralBinding.id)
        .where(ReferralBinding.referrer_id == owner.id)
        .limit(1)
    ):
        return None
    code = code_of(db, owner=owner)
    link = invite_link(code=str(code.code)) if code is not None else ""
    rewards = plan_rewards(db)
    top = None
    if rewards:
        same = [row for row in rewards if row.currency == settings.billing_currency]
        pool = same or [row for row in rewards if row.currency == rewards[0].currency]
        top = max(pool, key=lambda row: row.bonus_minor)
    return InviteOffer(
        link=link,
        share_url=share_url(link=link) if link else "",
        top_bonus=top,
        percent=REFERRAL_PERCENT,
    )


InvitedState = Literal["paid", "trial", "unpaid"]


@dataclass(frozen=True, slots=True)
class InvitedRow:
    binding: ReferralBinding
    state: InvitedState
    first_bill: Invoice | None
    reward: ReferralReward | None

    @property
    def first_minor(self) -> int:
        if self.reward is not None:
            return self.reward.base_minor
        if self.first_bill is None:
            return 0
        bill = self.first_bill
        return bill.amount_minor + bill.wallet_minor + bill.credit_minor


def invited_rows(
    db: Session, *, owner: User, bindings: Sequence[ReferralBinding], now: datetime
) -> list[InvitedRow]:
    from app.modules.billing.selectors import first_payments, on_trial

    ids = [binding.owner_id for binding in bindings]
    firsts = first_payments(db, owner_ids=ids)
    trials = on_trial(db, owner_ids=ids, now=now)
    rewards = {
        reward.binding_id: reward
        for reward in db.scalars(
            select(ReferralReward).where(
                ReferralReward.owner_id == owner.id,
                ReferralReward.binding_id.in_([b.id for b in bindings]),
            )
        )
    }
    rows = []
    for binding in bindings:
        first = firsts.get(binding.owner_id)
        state: InvitedState = "unpaid"
        if first is not None:
            state = "paid"
        elif binding.owner_id in trials:
            state = "trial"
        rows.append(InvitedRow(binding, state, first, rewards.get(binding.id)))
    return rows


def invited_paid_count(db: Session, *, owner: User) -> int:
    from app.modules.billing.selectors import paid_count

    ids: list[uuid.UUID] = list(
        db.scalars(
            select(ReferralBinding.owner_id).where(
                ReferralBinding.referrer_id == owner.id
            )
        )
    )
    return paid_count(db, owner_ids=ids)


__all__ = [
    "FeedbackKind",
    "FeedbackOffer",
    "FeedbackReward",
    "InviteOffer",
    "InvitedRow",
    "PlanReward",
    "WalletBalance",
    "WalletCounts",
    "access_of",
    "available_minor",
    "code_of",
    "code_owner",
    "feedback_history",
    "feedback_offer",
    "feedback_prompt_due",
    "invite_link",
    "invite_offer",
    "invited_paid_count",
    "invited_rows",
    "invited_users",
    "inviter_of",
    "last_answered_feedback",
    "may_invite",
    "may_withdraw",
    "open_withdrawal",
    "payout_history",
    "plan_rewards",
    "referral_mode",
    "reward_history",
    "share_url",
    "spend_history",
    "spendable_minor",
    "wallet_balance",
    "wallet_counts",
]
