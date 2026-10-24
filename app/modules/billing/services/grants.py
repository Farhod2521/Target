"""Days, plans, pages and promos given rather than paid for; trials and setup."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    MAX_GRANT_DAYS,
    MAX_SLOT_CHANGE,
    REDEMPTION_STATUS_LABELS,
    TRIAL_DAYS,
    HistoryKind,
    PlanMove,
    RedemptionStatus,
    SubscriptionStatus,
)
from app.modules.billing.exceptions import (
    CheaperPlanWaits,
    DaysOutOfRange,
    NoSlotsToTake,
    NothingToExtend,
    PlanNotOpened,
    PromoAlreadyUsed,
    PromoNotFound,
    PromoNotRedeemable,
    PromoUsedUp,
    ReasonRequired,
    RedemptionNotPending,
    SetupIncomplete,
    SlotsOutOfRange,
    SubscriptionExpired,
)
from app.modules.billing.models import Plan, PromoCode, PromoRedemption, Subscription
from app.modules.billing.selectors import (
    chosen_account,
    has_ever_subscribed,
    has_live_subscription,
    live_promo,
    may_prepare,
    plan_switch,
    prepared_account,
    setup_locked,
    times_used,
    times_used_by,
    unseen_redemption,
)
from app.modules.billing.services.entitlement import (
    apply_grant,
    default_plan,
    land_plan,
    latest_locked,
    locked_entitlement,
    open_entitlement,
    open_promo_entitlement,
    opens_subscription,
    record_change,
    require_grantable,
)

logger = logging.getLogger(__name__)
SUBSCRIPTION = "subscription"


def require_live_subscription(db: Session, *, owner: User) -> None:
    if has_live_subscription(db, owner=owner):
        return
    if has_ever_subscribed(db, owner=owner):
        raise SubscriptionExpired
    raise PlanNotOpened


def require_preparation(db: Session, *, owner: User) -> None:
    if not may_prepare(db, owner=owner):
        require_live_subscription(db, owner=owner)


def require_setup_completed(db: Session, *, owner: User) -> None:
    if not setup_locked(db, owner=owner):
        raise SetupIncomplete


def acknowledge_promo(
    db: Session, *, owner: User, redemption_id: str, now: datetime
) -> PromoRedemption | None:
    waiting = unseen_redemption(db, owner=owner)
    if waiting is None or str(waiting.id) != redemption_id:
        return None
    waiting.acknowledged_at = now
    db.flush()
    return waiting


def start_trial(db: Session, *, user: User, now: datetime) -> Subscription:
    account = prepared_account(db, owner=user)
    subscription = Subscription(
        owner_id=user.id,
        plan_id=default_plan(db).id,
        ad_account_id=account.id if account else None,
        setup_completed_at=user.prepared_at,
        status=SubscriptionStatus.TRIAL,
        extra_pages=0,
        started_at=now,
        expires_at=now + timedelta(days=TRIAL_DAYS),
        note="",
    )
    db.add(subscription)
    db.flush()
    db.refresh(subscription)
    record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.TRIAL,
        from_plan=None,
        move=PlanMove.RESTART,
        days=TRIAL_DAYS,
        expires_before=None,
        now=now,
    )
    emit(
        db,
        owner_id=user.id,
        name=EventName.SUBSCRIPTION_TRIAL_STARTED,
        aggregate_type="subscription",
        aggregate_id=subscription.id,
        payload={
            "plan": subscription.plan.code,
            "trial_days": TRIAL_DAYS,
            "expires_at": subscription.expires_at.isoformat(),
        },
    )
    return subscription


def complete_setup(db: Session, *, owner: User, now: datetime) -> Subscription | None:
    subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
        )
        .limit(1)
        .with_for_update(of=Subscription)
    )
    if subscription is None:
        if has_ever_subscribed(db, owner=owner):
            raise SubscriptionExpired
        locked = db.get(User, owner.id, with_for_update=True)
        assert locked is not None
        if locked.prepared_at is not None:
            owner.prepared_at = locked.prepared_at
            return None
        locked.prepared_at = now
        owner.prepared_at = now
        chosen = prepared_account(db, owner=owner)
        emit(
            db,
            owner_id=owner.id,
            name=EventName.SETUP_COMPLETED,
            aggregate_type="user",
            aggregate_id=owner.id,
            payload={
                "ad_account_external_id": chosen.external_id if chosen else "",
                "plan": "",
            },
            occurred_at=now,
        )
        db.flush()
        return None
    if subscription.ad_account_id is None:
        account = chosen_account(db, owner=owner)
        subscription.ad_account_id = account.id if account else None
    if subscription.setup_completed_at is not None:
        db.flush()
        return subscription
    subscription.setup_completed_at = now
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.SETUP_COMPLETED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "ad_account_external_id": (
                subscription.ad_account.external_id if subscription.ad_account else ""
            ),
            "plan": subscription.plan.code,
        },
        occurred_at=now,
    )
    return subscription


def _note(existing: str, line: str) -> str:
    return f"{existing}\n{line}".strip()


def grant_days(
    db: Session, *, owner: User, days: int, actor: User, reason: str, now: datetime
) -> Subscription:
    if not reason.strip():
        raise ReasonRequired
    if days < 1 or days > MAX_GRANT_DAYS:
        raise DaysOutOfRange(limit=MAX_GRANT_DAYS)
    subscription = latest_locked(db, owner=owner)
    if subscription is None:
        raise NothingToExtend
    previous = subscription.expires_at
    subscription.expires_at = max(previous, now) + timedelta(days=days)
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.canceled_at = None
    subscription.ended_at = None
    subscription.activated_by_id = actor.id
    subscription.note = _note(
        subscription.note,
        f"{now:%d.%m.%Y} · +{days} · {actor.email} · {reason.strip()}",
    )
    db.flush()
    record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.GIVEN,
        from_plan=subscription.plan,
        move=PlanMove.STACK,
        days=days,
        expires_before=previous,
        now=now,
        actor=actor,
        reason=reason,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.SUBSCRIPTION_EXTENDED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "days": days,
            "from": previous.isoformat(),
            "to": subscription.expires_at.isoformat(),
            "plan": subscription.plan.code,
            "reason": reason.strip(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return subscription


def grant_plan(
    db: Session, *, owner: User, plan: Plan, actor: User, reason: str, now: datetime
) -> Subscription:
    if not reason.strip():
        raise ReasonRequired
    days = plan.period_days
    subscription = locked_entitlement(db, owner=owner)
    before_plan = subscription.plan if subscription is not None else None
    before = subscription.expires_at if subscription is not None else None
    previous = before_plan.code if before_plan is not None else ""
    if subscription is None:
        subscription = open_entitlement(db, owner=owner, plan=plan, days=days, now=now)
        move = PlanMove.RESTART
    else:
        until = plan_switch(db, owner=owner, plan=plan, now=now).until
        if until is not None:
            raise CheaperPlanWaits(until=until)
        move = land_plan(db, subscription=subscription, plan=plan, days=days, now=now)
    subscription.activated_by_id = actor.id
    subscription.note = _note(
        subscription.note,
        f"{now:%d.%m.%Y} · {plan.code} +{days} · {actor.email} · {reason.strip()}",
    )
    db.flush()
    record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.GIVEN,
        from_plan=before_plan,
        move=move,
        days=days,
        expires_before=before,
        now=now,
        actor=actor,
        reason=reason,
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.SUBSCRIPTION_PLAN_CHANGED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "from": previous,
            "to": plan.code,
            "days": days,
            "expires_at": subscription.expires_at.isoformat(),
            "reason": reason.strip(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return subscription


def _pages_decided(
    db: Session, *, owner: User, pages: int, reason: str
) -> Subscription:
    if not reason.strip():
        raise ReasonRequired
    if pages < 1 or pages > MAX_SLOT_CHANGE:
        raise SlotsOutOfRange(limit=MAX_SLOT_CHANGE)
    subscription = latest_locked(db, owner=owner)
    if subscription is None:
        raise NothingToExtend
    return subscription


def _pages_write(
    db: Session,
    *,
    subscription: Subscription,
    delta: int,
    actor: User,
    reason: str,
    now: datetime,
) -> Subscription:
    previous = subscription.extra_pages
    subscription.extra_pages = previous + delta
    subscription.note = _note(
        subscription.note,
        f"{now:%d.%m.%Y} · {delta:+d} o'rin · {actor.email} · {reason.strip()}",
    )
    db.flush()
    emit(
        db,
        owner_id=subscription.owner_id,
        name=EventName.SUBSCRIPTION_SLOTS_CHANGED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "from": previous,
            "to": subscription.extra_pages,
            "plan": subscription.plan.code,
            "reason": reason.strip(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    return subscription


def grant_pages(
    db: Session, *, owner: User, pages: int, actor: User, reason: str, now: datetime
) -> Subscription:
    subscription = _pages_decided(db, owner=owner, pages=pages, reason=reason)
    return _pages_write(
        db, subscription=subscription, delta=pages, actor=actor, reason=reason, now=now
    )


def revoke_pages(
    db: Session, *, owner: User, pages: int, actor: User, reason: str, now: datetime
) -> Subscription:
    subscription = _pages_decided(db, owner=owner, pages=pages, reason=reason)
    if subscription.extra_pages < pages:
        raise NoSlotsToTake(held=subscription.extra_pages)
    return _pages_write(
        db, subscription=subscription, delta=-pages, actor=actor, reason=reason, now=now
    )


@dataclass(frozen=True, slots=True)
class Redeemed:
    days: int
    pages: int
    plan_changed: bool
    pending: bool = False


def redeem_promo(db: Session, *, user: User, code: str, now: datetime) -> Redeemed:
    promo = live_promo(db, code=code, now=now)
    if promo is None:
        raise PromoNotFound
    if not promo.grants_anything:
        raise PromoNotRedeemable
    subscription = latest_locked(db, owner=user)
    if subscription is None and not opens_subscription(promo=promo):
        raise NothingToExtend
    require_grantable(db, subscription=subscription, promo=promo, now=now)
    if promo.max_uses_per_user and times_used_by(db, promo=promo, owner=user) >= (
        promo.max_uses_per_user
    ):
        raise PromoAlreadyUsed
    if promo.max_uses and times_used(db, promo=promo) >= promo.max_uses:
        raise PromoUsedUp
    if promo.needs_approval:
        return _request(db, promo=promo, user=user, subscription=subscription, now=now)
    return _hand_over(db, promo=promo, user=user, subscription=subscription, now=now)


def _redemption(
    *,
    promo: PromoCode,
    user: User,
    subscription: Subscription | None,
    status: str,
    now: datetime,
) -> PromoRedemption:
    return PromoRedemption(
        owner_id=user.id,
        promo_id=promo.id,
        subscription_id=subscription.id if subscription else None,
        status=status,
        granted_days=0,
        granted_pages=0,
        discount_minor=0,
        decision_note="",
        redeemed_at=now,
    )


def _request(
    db: Session,
    *,
    promo: PromoCode,
    user: User,
    subscription: Subscription | None,
    now: datetime,
) -> Redeemed:
    db.add(
        _redemption(
            promo=promo,
            user=user,
            subscription=subscription,
            status=RedemptionStatus.PENDING,
            now=now,
        )
    )
    emit(
        db,
        owner_id=user.id,
        name=EventName.PROMO_REQUESTED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id if subscription is not None else user.id,
        payload={
            "code": promo.code,
            "kind": promo.kind,
            "days": promo.grant_days,
            "pages": promo.grant_pages,
        },
        occurred_at=now,
    )
    db.flush()
    return Redeemed(
        days=promo.grant_days,
        pages=promo.grant_pages,
        plan_changed=promo.plan_id is not None,
        pending=True,
    )


def _hand_over(
    db: Session,
    *,
    promo: PromoCode,
    user: User,
    subscription: Subscription | None,
    now: datetime,
) -> Redeemed:
    from_plan = subscription.plan if subscription is not None else None
    if subscription is None:
        subscription = open_promo_entitlement(db, owner=user, promo=promo, now=now)
    plan_changed = apply_grant(
        db,
        subscription=subscription,
        promo=promo,
        from_plan=from_plan,
        actor=None,
        now=now,
    )
    row = _redemption(
        promo=promo,
        user=user,
        subscription=subscription,
        status=RedemptionStatus.APPROVED,
        now=now,
    )
    row.granted_days = promo.grant_days
    row.granted_pages = promo.grant_pages
    db.add(row)
    emit(
        db,
        owner_id=user.id,
        name=EventName.PROMO_REDEEMED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "code": promo.code,
            "days": promo.grant_days,
            "pages": promo.grant_pages,
            "plan": subscription.plan.code,
            "expires_at": subscription.expires_at.isoformat(),
        },
        occurred_at=now,
    )
    db.flush()
    return Redeemed(
        days=promo.grant_days, pages=promo.grant_pages, plan_changed=plan_changed
    )


def redeemed_summary(result: Redeemed) -> str:
    parts = []
    if result.days:
        parts.append("%(days)s kun" % {"days": result.days})
    if result.pages:
        parts.append("%(count)s ta sahifa o'rni" % {"count": result.pages})
    if result.plan_changed:
        parts.append("tarif")
    listed = " · ".join(parts)
    if result.pending:
        return "So'rovingiz qabul qilindi: %(items)s. Tasdiqlanishini kuting." % {
            "items": listed
        }
    return "Qo'shildi: %(items)s" % {"items": listed}


def _locked_redemption(db: Session, *, redemption: PromoRedemption) -> PromoRedemption:
    locked = db.get(PromoRedemption, redemption.id, with_for_update=True)
    assert locked is not None
    if locked.status != RedemptionStatus.PENDING:
        raise RedemptionNotPending(
            decision=str(REDEMPTION_STATUS_LABELS.get(locked.status, locked.status))
        )
    return locked


def approve_redemption(
    db: Session, *, redemption: PromoRedemption, actor: User, now: datetime
) -> PromoRedemption:
    locked = _locked_redemption(db, redemption=redemption)
    promo = locked.promo
    owner = db.get(User, locked.owner_id)
    assert owner is not None
    subscription = latest_locked(db, owner=owner)
    from_plan = subscription.plan if subscription is not None else None
    if subscription is None:
        if not opens_subscription(promo=promo):
            raise NothingToExtend
        subscription = open_promo_entitlement(db, owner=owner, promo=promo, now=now)
    apply_grant(
        db,
        subscription=subscription,
        promo=promo,
        from_plan=from_plan,
        actor=actor,
        now=now,
    )
    locked.status = RedemptionStatus.APPROVED
    locked.subscription_id = subscription.id
    locked.granted_days = promo.grant_days
    locked.granted_pages = promo.grant_pages
    locked.decided_by_id = actor.id
    locked.decided_at = now
    emit(
        db,
        owner_id=owner.id,
        name=EventName.PROMO_REDEEMED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "code": promo.code,
            "days": promo.grant_days,
            "pages": promo.grant_pages,
            "plan": subscription.plan.code,
            "expires_at": subscription.expires_at.isoformat(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    db.flush()
    return locked


def reject_redemption(
    db: Session, *, redemption: PromoRedemption, actor: User, reason: str, now: datetime
) -> PromoRedemption:
    if not reason.strip():
        raise ReasonRequired
    locked = _locked_redemption(db, redemption=redemption)
    locked.status = RedemptionStatus.REJECTED
    locked.decision_note = reason.strip()
    locked.decided_by_id = actor.id
    locked.decided_at = now
    emit(
        db,
        owner_id=locked.owner_id,
        name=EventName.PROMO_REJECTED,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=locked.id,
        payload={
            "code": locked.promo.code,
            "reason": reason.strip(),
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    db.flush()
    return locked
