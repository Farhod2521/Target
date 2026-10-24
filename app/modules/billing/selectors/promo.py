from dataclasses import dataclass
from datetime import datetime
from typing import Any

from llmkit import MICROS_PER_MINOR
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.audit.constants import LLMCallStatus, LLMPurpose
from app.modules.audit.models import LLMCall
from app.modules.billing.constants import (
    CHAT_SHARE_PCT,
    HELD_REDEMPTION_STATUSES,
    UNPAID_END_STATUSES,
    InvoiceStatus,
    PromoDiscountKind,
    PromoKind,
    PromoScope,
    RedemptionStatus,
)
from app.modules.billing.exceptions import (
    PromoAlreadyUsed,
    PromoNotApplicable,
    PromoNotFound,
    PromoUsedUp,
)
from app.modules.billing.models import Invoice, Plan, PromoCode, PromoRedemption
from app.modules.billing.models.promo_code import normalise
from app.modules.billing.selectors.subscription import live_subscription


def live_promo(db: Session, *, code: str, now: datetime) -> PromoCode | None:
    normalised = normalise(code)
    if not normalised:
        return None
    return db.scalar(
        select(PromoCode).where(
            PromoCode.code == normalised,
            PromoCode.is_active.is_(True),
            or_(PromoCode.starts_at.is_(None), PromoCode.starts_at <= now),
            or_(PromoCode.expires_at.is_(None), PromoCode.expires_at > now),
        )
    )


def counted_redemptions() -> Select[tuple[PromoRedemption]]:
    unpaid = select(Invoice.id).where(Invoice.status.in_(UNPAID_END_STATUSES))
    return select(PromoRedemption).where(
        or_(
            PromoRedemption.invoice_id.is_(None),
            PromoRedemption.invoice_id.not_in(unpaid),
        )
    )


def _count(db: Session, query: Select[tuple[PromoRedemption]]) -> int:
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def times_used(db: Session, *, promo: PromoCode) -> int:
    return _count(
        db,
        counted_redemptions().where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.status.in_(HELD_REDEMPTION_STATUSES),
        ),
    )


def times_used_by(db: Session, *, promo: PromoCode, owner: User) -> int:
    return _count(
        db,
        counted_redemptions().where(
            PromoRedemption.owner_id == owner.id, PromoRedemption.promo_id == promo.id
        ),
    )


def pending_redemption(db: Session, *, owner: User) -> PromoRedemption | None:
    return db.scalar(
        select(PromoRedemption)
        .where(
            PromoRedemption.owner_id == owner.id,
            PromoRedemption.status == RedemptionStatus.PENDING,
        )
        .order_by(PromoRedemption.redeemed_at.desc())
        .limit(1)
    )


def unseen_redemption(db: Session, *, owner: User) -> PromoRedemption | None:
    with_plan = select(PromoCode.id).where(PromoCode.plan_id.is_not(None))
    return db.scalar(
        select(PromoRedemption)
        .where(
            PromoRedemption.owner_id == owner.id,
            PromoRedemption.status == RedemptionStatus.APPROVED,
            PromoRedemption.acknowledged_at.is_(None),
            or_(
                PromoRedemption.granted_days > 0,
                PromoRedemption.granted_pages > 0,
                PromoRedemption.promo_id.in_(with_plan),
            ),
        )
        .order_by(PromoRedemption.redeemed_at.desc())
        .limit(1)
    )


@dataclass(frozen=True, slots=True)
class DiscountQuote:
    promo: PromoCode
    base_minor: int
    discount_minor: int
    currency: str

    @property
    def total_minor(self) -> int:
        return self.base_minor - self.discount_minor

    @property
    def percent(self) -> int:
        if self.promo.discount_kind == PromoDiscountKind.PERCENT:
            return self.promo.discount_value
        return 0


def discount_quote(
    db: Session,
    *,
    owner: User,
    code: str,
    base_minor: int,
    currency: str,
    now: datetime,
) -> DiscountQuote:
    promo = live_promo(db, code=code, now=now)
    if promo is None:
        raise PromoNotFound
    if promo.kind != PromoKind.DISCOUNT or promo.needs_approval:
        raise PromoNotApplicable
    if promo.scope not in (PromoScope.SUBSCRIPTION, PromoScope.BOTH):
        raise PromoNotApplicable
    if base_minor < promo.min_amount_minor:
        raise PromoNotApplicable
    movable = len(movable_discounts(db, owner=owner, promo=promo))
    mine = times_used_by(db, promo=promo, owner=owner) - movable
    if promo.max_uses_per_user and mine >= promo.max_uses_per_user:
        raise PromoAlreadyUsed
    if promo.max_uses and times_used(db, promo=promo) - movable >= promo.max_uses:
        raise PromoUsedUp
    return DiscountQuote(
        promo=promo,
        base_minor=base_minor,
        discount_minor=_discount_of(promo=promo, base_minor=base_minor),
        currency=currency,
    )


def discount_code(db: Session, *, code: str, now: datetime) -> PromoCode | None:
    promo = live_promo(db, code=code, now=now)
    if promo is None or promo.kind != PromoKind.DISCOUNT:
        return None
    return promo


def movable_discounts(
    db: Session, *, owner: User, promo: PromoCode
) -> list[PromoRedemption]:
    pending = select(Invoice.id).where(Invoice.status == InvoiceStatus.PENDING)
    return list(
        db.scalars(
            select(PromoRedemption).where(
                PromoRedemption.owner_id == owner.id,
                PromoRedemption.promo_id == promo.id,
                PromoRedemption.invoice_id.in_(pending),
            )
        )
    )


def _discount_of(*, promo: PromoCode, base_minor: int) -> int:
    value = promo.discount_value
    if promo.discount_kind == PromoDiscountKind.PERCENT and value > 0:
        discount = base_minor * value // 100
    elif promo.discount_kind == PromoDiscountKind.AMOUNT and value > 0:
        discount = value
    else:
        raise PromoNotApplicable
    if discount <= 0 or discount >= base_minor:
        raise PromoNotApplicable
    return discount


@dataclass(frozen=True, slots=True)
class Announcement:
    redemption: PromoRedemption
    free_slots: int
    choices: tuple[Any, ...]

    @property
    def can_choose(self) -> bool:
        return self.free_slots > 0 and bool(self.choices)


def promo_announcement(
    db: Session, *, owner: User, now: datetime
) -> Announcement | None:
    from app.modules.integrations.selectors import page_slots, pages_on_offer

    redemption = unseen_redemption(db, owner=owner)
    if redemption is None:
        return None
    slots = page_slots(db, owner=owner)
    if not slots.has_room:
        return Announcement(redemption=redemption, free_slots=slots.free, choices=())
    return Announcement(
        redemption=redemption,
        free_slots=slots.free,
        choices=pages_on_offer(db, owner=owner),
    )


@dataclass(frozen=True, slots=True)
class AiBudget:
    limit_minor: int
    spent_minor: int
    currency: str
    entitled: bool

    @property
    def is_exhausted(self) -> bool:
        if not self.entitled:
            return True
        return self.limit_minor > 0 and self.spent_minor >= self.limit_minor

    @property
    def chat_is_exhausted(self) -> bool:
        if not self.entitled:
            return True
        if self.limit_minor <= 0:
            return False
        return self.spent_minor >= self.limit_minor * CHAT_SHARE_PCT // 100

    @property
    def remaining_minor(self) -> int:
        if self.limit_minor <= 0:
            return 0
        return max(0, self.limit_minor - self.spent_minor)


def ai_budget(db: Session, *, owner: User, now: datetime) -> AiBudget:
    subscription = live_subscription(db, owner=owner)
    plan: Plan | None = subscription.plan if subscription is not None else None
    return AiBudget(
        limit_minor=int(getattr(plan, "llm_cost_limit_minor", 0) or 0),
        spent_minor=spent_this_month(db, owner=owner, now=now),
        currency=settings.anthropic_price_currency,
        entitled=subscription is not None,
    )


def spent_this_month(db: Session, *, owner: User, now: datetime) -> int:
    from app.modules.audit.selectors import exact_cost

    since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.scalar(
        select(func.sum(exact_cost())).where(
            LLMCall.owner_id == owner.id,
            LLMCall.purpose.in_(
                (
                    LLMPurpose.DECISION,
                    LLMPurpose.CHAT,
                    LLMPurpose.REPORT,
                    LLMPurpose.DAILY_REPORT,
                )
            ),
            LLMCall.created_at >= since,
            LLMCall.status != LLMCallStatus.RATE_LIMITED,
        )
    )
    return int(total or 0) // MICROS_PER_MINOR


@dataclass(frozen=True, slots=True)
class ChatAllowance:
    limit: int
    used: int

    @property
    def is_exhausted(self) -> bool:
        return self.limit > 0 and self.used >= self.limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used) if self.limit > 0 else -1


def chat_allowance(db: Session, *, owner: User, now: datetime) -> ChatAllowance:
    subscription = live_subscription(db, owner=owner)
    plan = subscription.plan if subscription is not None else None
    limit = int(getattr(plan, "daily_chat_requests", 0) or 0)
    return ChatAllowance(
        limit=limit,
        used=chat_requests_today(db, owner=owner, now=now) if limit > 0 else 0,
    )


def chat_requests_today(db: Session, *, owner: User, now: datetime) -> int:
    since = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        db.scalar(
            select(func.count())
            .select_from(LLMCall)
            .where(
                LLMCall.owner_id == owner.id,
                LLMCall.purpose == LLMPurpose.CHAT,
                LLMCall.status == LLMCallStatus.OK,
                LLMCall.created_at >= since,
            )
        )
        or 0
    )
