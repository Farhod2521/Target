"""Every write the sales board makes.

Each function flushes and leaves the commit to its caller - the router or the
task - which is where Django's ``transaction.atomic`` ended.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.hooks import on
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.services import emit
from app.modules.backoffice.constants import ActionKind
from app.modules.public.models import ConsultRequest
from app.modules.sales.constants import (
    ACTION_TARGET_PROVIDER,
    AWAITING_EXTRA_DAYS,
    CLAIM_DAYS,
    HOLD_DAYS,
    NO_ANSWER_HOLD_DAYS,
    NO_ANSWER_LIMIT,
    SELLING_STAGES,
    ActivityKind,
    Group,
    HoldTerm,
    LiftKind,
    Outcome,
    Source,
    Stage,
)
from app.modules.sales.exceptions import (
    AlreadyClaimed,
    AlreadyContacted,
    CallbackInPast,
    CallbackRequired,
    HoldGone,
    NoteRequired,
    NothingToReopen,
    NotInQueue,
    NotYourCard,
    ReasonRequired,
)
from app.modules.sales.models import (
    ContactHold,
    LostReason,
    SalesActivity,
    SalesClaim,
    SalesCommission,
    SalesMonth,
    SaleSource,
    SalesRule,
    SalesSegment,
)
from app.modules.sales.selectors import (
    Span,
    consult_by_id,
    current_span,
    figure_month,
    group_now,
    month_start,
    referral_paid,
    rule_at,
    segments,
    source_of,
    span_of,
    subject_q,
)
from app.modules.sales.services._cards import (
    AGGREGATE,
    announce,
    close,
    hold,
    journal,
    locked_card,
    trail,
)

logger = logging.getLogger(__name__)
CATCH_UP_MONTHS = 24
REOPENABLE = (Outcome.LOST, Outcome.UNREACHABLE)


# -- taking and moving a card -------------------------------------------------


def _subject(db: Session, *, client_id: uuid.UUID, group: str) -> dict[str, uuid.UUID]:
    if group == Group.ARIZA and consult_by_id(db, consult_id=client_id) is not None:
        return {"consult_id": client_id}
    return {"owner_id": client_id}


def claim_client(
    db: Session, *, manager: User, client_id: uuid.UUID, now: datetime
) -> SalesClaim:
    rule = rule_at(db, at=now)
    group = group_now(
        db,
        client_id=client_id,
        now=now,
        ending_days=rule.ending_days,
        extra=segments(db),
    )
    if group is None:
        taken = db.scalar(
            select(SalesClaim.id)
            .where(subject_q(SalesClaim, client_id), SalesClaim.closed_at.is_(None))
            .limit(1)
        )
        if taken is not None:
            raise AlreadyClaimed
        raise NotInQueue
    claim = SalesClaim(
        **_subject(db, client_id=client_id, group=group),
        manager_id=manager.id,
        group=group,
        claimed_at=now,
        expires_at=now + timedelta(days=CLAIM_DAYS),
    )
    try:
        with db.begin_nested():
            db.add(claim)
    except IntegrityError as exc:
        raise AlreadyClaimed from exc
    journal(
        db,
        claim=claim,
        actor=manager,
        kind=ActionKind.SALES_CLAIMED,
        detail={"group": group, "claim": str(claim.id)},
    )
    trail(
        db,
        claim=claim,
        actor=manager,
        kind=ActivityKind.CLAIMED,
        now=now,
        event=EventName.SALES_CLAIMED,
        payload={"group": group},
    )
    return claim


def add_note(
    db: Session, *, manager: User, client_id: uuid.UUID, body: str, now: datetime
) -> SalesActivity:
    if not body.strip():
        raise NoteRequired
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.updated_at = now
    return trail(
        db, claim=claim, actor=manager, kind=ActivityKind.NOTE, body=body, now=now
    )


def _schedule_call(
    db: Session,
    *,
    manager: User,
    client_id: uuid.UUID,
    stage: Stage,
    kind: ActivityKind,
    callback_at: datetime | None,
    reason: LostReason | None,
    note: str,
    now: datetime,
) -> SalesClaim:
    if callback_at is None:
        raise CallbackRequired
    if callback_at <= now:
        raise CallbackInPast
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.stage = str(stage)
    claim.callback_at = callback_at
    claim.attempts = 0
    claim.contacted_at = claim.contacted_at or now
    if reason is not None:
        claim.reason_id = reason.id
    db.flush()
    trail(
        db,
        claim=claim,
        actor=manager,
        kind=kind,
        reason=reason,
        body=note,
        callback_at=callback_at,
        now=now,
    )
    return claim


def mark_callback(
    db: Session,
    *,
    manager: User,
    client_id: uuid.UUID,
    callback_at: datetime | None,
    note: str,
    now: datetime,
) -> SalesClaim:
    return _schedule_call(
        db,
        manager=manager,
        client_id=client_id,
        stage=Stage.CALLBACK,
        kind=ActivityKind.CALLBACK,
        callback_at=callback_at,
        reason=None,
        note=note,
        now=now,
    )


def mark_thinking(
    db: Session,
    *,
    manager: User,
    client_id: uuid.UUID,
    callback_at: datetime | None,
    reason: LostReason | None,
    note: str,
    now: datetime,
) -> SalesClaim:
    return _schedule_call(
        db,
        manager=manager,
        client_id=client_id,
        stage=Stage.THINKING,
        kind=ActivityKind.THINKING,
        callback_at=callback_at,
        reason=reason,
        note=note,
        now=now,
    )


def mark_awaiting(
    db: Session, *, manager: User, client_id: uuid.UUID, note: str, now: datetime
) -> SalesClaim:
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.stage = str(Stage.AWAITING)
    claim.attempts = 0
    claim.contacted_at = claim.contacted_at or now
    extended = claim.extended_at is None
    if extended:
        claim.extended_at = now
        claim.expires_at = claim.expires_at + timedelta(days=AWAITING_EXTRA_DAYS)
    db.flush()
    trail(
        db,
        claim=claim,
        actor=manager,
        kind=ActivityKind.AWAITING,
        body=note,
        now=now,
        payload={"extended": extended},
    )
    return claim


def mark_using(
    db: Session, *, manager: User, client_id: uuid.UUID, note: str, now: datetime
) -> SalesClaim:
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.stage = str(Stage.USING)
    claim.attempts = 0
    claim.contacted_at = claim.contacted_at or now
    db.flush()
    trail(db, claim=claim, actor=manager, kind=ActivityKind.USING, body=note, now=now)
    return claim


def move_to_taken(
    db: Session, *, manager: User, client_id: uuid.UUID, note: str, now: datetime
) -> SalesClaim:
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.stage = str(Stage.TAKEN)
    db.flush()
    trail(
        db, claim=claim, actor=manager, kind=ActivityKind.TAKEN_BACK, body=note, now=now
    )
    return claim


def record_no_answer(
    db: Session, *, manager: User, client_id: uuid.UUID, note: str, now: datetime
) -> SalesClaim:
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.attempts += 1
    claim.stage = str(Stage.NO_ANSWER)
    db.flush()
    if claim.attempts < NO_ANSWER_LIMIT:
        trail(
            db,
            claim=claim,
            actor=manager,
            kind=ActivityKind.NO_ANSWER,
            body=note,
            now=now,
            payload={"attempts": claim.attempts},
        )
        return claim
    close(db, claim=claim, outcome=Outcome.UNREACHABLE, now=now)
    hold(
        db,
        claim=claim,
        until=now + timedelta(days=NO_ANSWER_HOLD_DAYS),
        set_by=manager,
        reason=None,
        now=now,
    )
    trail(
        db,
        claim=claim,
        actor=manager,
        kind=ActivityKind.UNREACHABLE,
        body=note,
        now=now,
        event=EventName.SALES_CARD_CLOSED,
        payload={"attempts": claim.attempts, "hold_days": NO_ANSWER_HOLD_DAYS},
    )
    return claim


def close_as_lost(
    db: Session,
    *,
    manager: User,
    client_id: uuid.UUID,
    reason: LostReason | None,
    term: HoldTerm,
    note: str,
    now: datetime,
) -> SalesClaim:
    if reason is None:
        raise ReasonRequired
    claim = locked_card(db, client_id=client_id, manager=manager)
    claim.contacted_at = claim.contacted_at or now
    close(db, claim=claim, outcome=Outcome.LOST, now=now, reason=reason)
    days = HOLD_DAYS.get(term)
    until = now + timedelta(days=days) if days is not None else None
    hold(db, claim=claim, until=until, set_by=manager, reason=reason, now=now)
    journal(
        db,
        claim=claim,
        actor=manager,
        kind=ActionKind.SALES_LOST,
        reason=reason.label,
        detail={"term": str(term), "claim": str(claim.id)},
    )
    trail(
        db,
        claim=claim,
        actor=manager,
        kind=ActivityKind.LOST,
        reason=reason,
        body=note,
        now=now,
        event=EventName.SALES_CARD_CLOSED,
        payload={"term": str(term)},
    )
    return claim


def return_to_pool(
    db: Session, *, manager: User, client_id: uuid.UUID, note: str, now: datetime
) -> SalesClaim:
    claim = locked_card(db, client_id=client_id, manager=manager)
    if claim.contacted_at is not None:
        raise AlreadyContacted
    close(db, claim=claim, outcome=Outcome.RETURNED, now=now)
    journal(
        db,
        claim=claim,
        actor=manager,
        kind=ActionKind.SALES_RETURNED,
        reason=note,
        detail={"claim": str(claim.id)},
    )
    trail(
        db,
        claim=claim,
        actor=manager,
        kind=ActivityKind.RETURNED,
        body=note,
        now=now,
        event=EventName.SALES_CARD_CLOSED,
    )
    return claim


def reopen_card(
    db: Session, *, manager: User, client_id: uuid.UUID, now: datetime
) -> SalesClaim:
    claim = db.scalars(
        select(SalesClaim)
        .where(
            subject_q(SalesClaim, client_id),
            SalesClaim.closed_at >= month_start(now=now),
            SalesClaim.outcome.in_([str(item) for item in REOPENABLE]),
        )
        .order_by(SalesClaim.closed_at.desc())
        .with_for_update()
        .limit(1)
    ).first()
    if claim is None:
        raise NothingToReopen
    if claim.manager_id != manager.id:
        raise NotYourCard
    try:
        with db.begin_nested():
            claim.closed_at = None
            claim.outcome = ""
            claim.attempts = 0
            claim.reason_id = None
            claim.expires_at = max(claim.expires_at, now + timedelta(days=CLAIM_DAYS))
    except IntegrityError as exc:
        db.expire(claim)
        raise AlreadyClaimed from exc
    db.execute(
        update(ContactHold)
        .where(ContactHold.claim_id == claim.id, ContactHold.lifted_at.is_(None))
        .values(
            lifted_at=now,
            lifted_by_id=manager.id,
            lift_kind=str(LiftKind.STAFF),
            updated_at=now,
        )
    )
    trail(db, claim=claim, actor=manager, kind=ActivityKind.REOPENED, now=now)
    return claim


def release_expired(db: Session, *, now: datetime) -> int:
    """Close every card whose week ran out; each in its own transaction."""
    due = list(
        db.scalars(
            select(SalesClaim.id).where(
                SalesClaim.closed_at.is_(None), SalesClaim.expires_at <= now
            )
        )
    )
    released = 0
    for pk in due:
        claim = db.scalars(
            select(SalesClaim)
            .where(
                SalesClaim.id == pk,
                SalesClaim.closed_at.is_(None),
                SalesClaim.expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        ).first()
        if claim is None:
            db.rollback()
            continue
        close(db, claim=claim, outcome=Outcome.EXPIRED, now=now)
        trail(
            db,
            claim=claim,
            actor=None,
            kind=ActivityKind.EXPIRED,
            now=now,
            event=EventName.SALES_CARD_CLOSED,
        )
        db.commit()
        released += 1
    if released:
        logger.info("sales cards released", extra={"count": released})
    return released


# -- holds ----------------------------------------------------------------------


def lift_hold(
    db: Session, *, hold_id: uuid.UUID, actor: User, now: datetime
) -> ContactHold:
    from app.modules.backoffice.services import record

    row = db.scalars(
        select(ContactHold)
        .where(ContactHold.id == hold_id, ContactHold.lifted_at.is_(None))
        .with_for_update()
    ).first()
    if row is None:
        raise HoldGone
    row.lifted_at = now
    row.lifted_by_id = actor.id
    row.lift_kind = str(LiftKind.STAFF)
    db.flush()
    if row.owner is not None:
        record(
            db,
            customer=row.owner,
            actor=actor,
            kind=ActionKind.SALES_HOLD_LIFTED,
            detail={"hold": str(row.id), "forever": row.until is None},
        )
        emit(
            db,
            owner_id=row.owner_id,
            name=EventName.SALES_HOLD_LIFTED,
            aggregate_type="sales_hold",
            aggregate_id=row.id,
            payload={"by": str(actor.id)},
            occurred_at=now,
        )
    announce(db, client_id=row.owner_id or row.consult_id)
    return row


def lift_on_payment(db: Session, *, client_id: uuid.UUID, now: datetime) -> int:
    return db.execute(
        update(ContactHold)
        .where(ContactHold.owner_id == client_id, ContactHold.lifted_at.is_(None))
        .values(lifted_at=now, lift_kind=str(LiftKind.PAID), updated_at=now)
    ).rowcount


# -- a request becoming an account ---------------------------------------------


def adopt_arizas(db: Session, *, user: User, now: datetime) -> int:
    """Hand the board's request cards for this number to the account."""
    if not user.phone or user.is_staff:
        return 0
    consults = list(
        db.scalars(
            select(ConsultRequest.id).where(ConsultRequest.phone_e164 == user.phone)
        )
    )
    if not consults:
        return 0
    cards = list(
        db.scalars(
            select(SalesClaim)
            .where(SalesClaim.owner_id.is_(None), SalesClaim.consult_id.in_(consults))
            .order_by(SalesClaim.claimed_at.desc())
            .with_for_update()
        )
    )
    card_ids = [str(card.id) for card in cards]
    taken = (
        db.scalar(
            select(SalesClaim.id)
            .where(SalesClaim.owner_id == user.id, SalesClaim.closed_at.is_(None))
            .limit(1)
        )
        is not None
    )
    for card in [card for card in cards if card.closed_at is None]:
        if not taken:
            taken = True
            continue
        _give_back(db, card, now=now)
    try:
        with db.begin_nested():
            for card in cards:
                card.owner_id = user.id
                card.updated_at = now
    except IntegrityError:
        for card in cards:
            db.refresh(card)
        for card in [card for card in cards if card.closed_at is None]:
            _give_back(db, card, now=now)
        for card in cards:
            card.owner_id = user.id
            card.updated_at = now
        db.flush()
    moved = len(cards)
    db.execute(
        update(SalesActivity)
        .where(SalesActivity.owner_id.is_(None), SalesActivity.consult_id.in_(consults))
        .values(owner_id=user.id)
    )
    db.execute(
        update(ContactHold)
        .where(ContactHold.owner_id.is_(None), ContactHold.consult_id.in_(consults))
        .values(owner_id=user.id, updated_at=now)
    )
    for consult_id in consults:
        announce(db, client_id=consult_id)
    announce(db, client_id=user.id)
    if moved:
        _log_adoption(db, user=user, consults=consults, cards=card_ids, now=now)
        logger.info(
            "sales arizas adopted", extra={"user_id": str(user.id), "cards": moved}
        )
    return moved


def _log_adoption(
    db: Session,
    *,
    user: User,
    consults: list[uuid.UUID],
    cards: list[str],
    now: datetime,
) -> None:
    from app.modules.audit.models import ActionLog

    detail = {"consult_ids": [str(pk) for pk in consults], "card_ids": cards}
    db.add(
        ActionLog(
            owner_id=user.id,
            actor_type=str(ActorType.SYSTEM),
            target_provider=ACTION_TARGET_PROVIDER,
            target_level="sales_claim",
            target_external_id=str(user.id),
            action=str(ActionType.SALES_ADOPT),
            request_payload=detail,
            previous_state={"owner_id": None, **detail},
            idempotency_key=f"sales-adopt:{user.id}:{round(now.timestamp() * 1000)}",
            status=str(ActionStatus.APPLIED),
            applied_at=now,
            dry_run=False,
        )
    )
    emit(
        db,
        owner_id=user.id,
        name=EventName.SALES_ARIZAS_ADOPTED,
        aggregate_type=AGGREGATE,
        aggregate_id=user.id,
        payload=detail,
        occurred_at=now,
    )


def _give_back(db: Session, card: SalesClaim, *, now: datetime) -> None:
    close(db, claim=card, outcome=Outcome.RETURNED, now=now)
    trail(
        db,
        claim=card,
        actor=None,
        kind=ActivityKind.RETURNED,
        now=now,
        event=EventName.SALES_CARD_CLOSED,
    )


@on("accounts.user_registered")
@on("accounts.phone_saved")
def _adopt_on_phone(*, db: Session, user: User, **_: Any) -> None:
    from app.common.db import utcnow

    adopt_arizas(db, user=user, now=utcnow())


# -- a paid bill ----------------------------------------------------------------


def credit_sale(db: Session, *, invoice: Any, now: datetime) -> SaleSource | None:
    """Write who sold this bill, pay the manager their share, close the card."""
    existing = source_of(db, invoice_id=invoice.id)
    if existing is not None:
        return existing
    if invoice.owner is not None:
        adopt_arizas(db, user=invoice.owner, now=now)
    claim = db.scalars(
        select(SalesClaim)
        .where(SalesClaim.owner_id == invoice.owner_id, SalesClaim.closed_at.is_(None))
        .with_for_update()
        .limit(1)
    ).first()
    lift_on_payment(db, client_id=invoice.owner_id, now=now)
    if invoice.amount_minor <= 0:
        if claim is not None:
            _close_card(db, claim=claim, invoice=invoice, sold=False, now=now)
        return None
    source = _source(db, claim=claim, invoice=invoice)
    manager = claim.manager if source == Source.MANAGER and claim else None
    row = SaleSource(
        owner_id=invoice.owner_id,
        invoice_id=invoice.id,
        source=str(source),
        manager_id=manager.id if manager else None,
        claim_id=claim.id if claim else None,
        paid_at=now,
    )
    db.add(row)
    db.flush()
    share = _share(db, manager=manager, claim=claim, invoice=invoice, now=now)
    if claim is not None:
        _close_card(db, claim=claim, invoice=invoice, sold=manager is not None, now=now)
    emit(
        db,
        owner_id=invoice.owner_id,
        name=EventName.SALES_CREDITED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "source": str(source),
            "manager_id": str(manager.id) if manager else "",
            "amount_minor": invoice.amount_minor,
            "currency": invoice.currency,
            "share_minor": share.amount_minor if share else 0,
            "percent": share.percent if share else 0,
        },
        occurred_at=now,
    )
    announce(db, client_id=invoice.owner_id)
    return row


def _source(db: Session, *, claim: SalesClaim | None, invoice: Any) -> Source:
    if referral_paid(db, invoice_id=invoice.id):
        return Source.REFERRAL
    if (
        claim is not None
        and claim.manager_id is not None
        and claim.stage in SELLING_STAGES
        and claim.contacted_at is not None
    ):
        return Source.MANAGER
    return Source.SELF


def _share(
    db: Session,
    *,
    manager: User | None,
    claim: SalesClaim | None,
    invoice: Any,
    now: datetime,
) -> SalesCommission | None:
    if manager is None:
        return None
    percent = rule_at(db, at=now).percent
    share = SalesCommission(
        owner_id=manager.id,
        client_id=invoice.owner_id,
        invoice_id=invoice.id,
        claim_id=claim.id if claim else None,
        base_minor=invoice.amount_minor,
        percent=percent,
        amount_minor=invoice.amount_minor * percent // 100,
        currency=invoice.currency,
        earned_at=now,
    )
    db.add(share)
    db.flush()
    logger.info(
        "sales share written",
        extra={
            "invoice": invoice.number,
            "manager_id": str(manager.id),
            "percent": percent,
            "share_minor": share.amount_minor,
        },
    )
    return share


def _close_card(
    db: Session, *, claim: SalesClaim, invoice: Any, sold: bool, now: datetime
) -> None:
    claim.invoice_id = invoice.id
    close(db, claim=claim, outcome=Outcome.SOLD if sold else Outcome.SELF_PAID, now=now)
    trail(
        db,
        claim=claim,
        actor=None,
        kind=ActivityKind.SOLD if sold else ActivityKind.SELF_PAID,
        now=now,
        event=EventName.SALES_CARD_CLOSED,
        payload={"invoice": invoice.number},
    )


# -- closing a month ------------------------------------------------------------


def close_months(db: Session, *, now: datetime) -> list[date]:
    current = current_span(now=now)
    closed = []
    for span in _finished(db, before=current):
        exists = db.scalar(
            select(SalesMonth.id).where(SalesMonth.month == span.month).limit(1)
        )
        if exists is not None:
            continue
        if _close_month(db, span=span, now=now):
            db.commit()
            closed.append(span.month)
        else:
            db.rollback()
    return closed


def _finished(db: Session, *, before: Span) -> list[Span]:
    first = db.scalar(select(func.min(SalesClaim.claimed_at)))
    if first is None:
        return []
    spans = []
    month = before.month
    for _ in range(CATCH_UP_MONTHS):
        month = date(month.year - (month.month == 1), (month.month - 2) % 12 + 1, 1)
        span = span_of(month)
        if span.end <= first:
            break
        spans.append(span)
    return list(reversed(spans))


def _close_month(db: Session, *, span: Span, now: datetime) -> bool:
    figures = figure_month(db, span=span)
    expected = (
        db.scalar(
            select(func.sum(SalesCommission.amount_minor)).where(
                SalesCommission.earned_at >= span.start,
                SalesCommission.earned_at < span.end,
            )
        )
        or 0
    )
    written = sum(item.commission_minor for item in figures)
    if written != expected:
        logger.error(
            "sales month does not add up",
            extra={"month": str(span.month), "written": written, "expected": expected},
        )
        return False
    for item in figures:
        manager = db.get(User, item.manager_id)
        if manager is None:
            continue
        db.add(
            SalesMonth(
                owner_id=manager.id,
                month=span.month,
                currency=item.currency,
                claimed=item.claimed,
                contacted=item.contacted,
                sold=item.sold,
                base_minor=item.base_minor,
                commission_minor=item.commission_minor,
                closed_at=now,
            )
        )
        emit(
            db,
            owner_id=manager.id,
            name=EventName.SALES_MONTH_CLOSED,
            aggregate_type="sales_month",
            aggregate_id=manager.id,
            payload={
                "month": span.month.isoformat(),
                "sold": item.sold,
                "commission_minor": item.commission_minor,
                "currency": item.currency,
            },
            occurred_at=now,
        )
    db.flush()
    logger.info("sales month closed", extra={"month": str(span.month)})
    return True


# -- the office's settings ------------------------------------------------------


def _settings_trail(
    db: Session, *, actor: User, what: str, detail: dict[str, Any], now: datetime
) -> None:
    from app.modules.backoffice.services import record

    record(
        db,
        customer=actor,
        actor=actor,
        kind=ActionKind.SALES_SETTINGS_CHANGED,
        reason=what,
        detail=detail,
    )
    emit(
        db,
        owner_id=actor.id,
        name=EventName.SALES_SETTINGS_CHANGED,
        aggregate_type="sales_settings",
        aggregate_id=actor.id,
        payload={"what": what, **detail},
        occurred_at=now,
    )


def set_rule(
    db: Session, *, actor: User, percent: int, ending_days: int, now: datetime
) -> SalesRule | None:
    current = rule_at(db, at=now)
    if current.set and (percent, ending_days) == (current.percent, current.ending_days):
        return None
    rule = SalesRule(
        percent=percent, ending_days=ending_days, valid_from=now, set_by_id=actor.id
    )
    db.add(rule)
    db.flush()
    _settings_trail(
        db,
        actor=actor,
        what="rule",
        detail={
            "percent": percent,
            "ending_days": ending_days,
            "was_percent": current.percent,
            "was_ending_days": current.ending_days,
        },
        now=now,
    )
    return rule


def set_ending_days(
    db: Session, *, actor: User, ending_days: int, now: datetime
) -> SalesRule | None:
    current = rule_at(db, at=now)
    return set_rule(
        db, actor=actor, percent=current.percent, ending_days=ending_days, now=now
    )


def add_reason(db: Session, *, actor: User, label: str, now: datetime) -> LostReason:
    last = db.scalar(select(func.max(LostReason.position))) or 0
    reason = LostReason(label=label.strip(), position=last + 1)
    db.add(reason)
    db.flush()
    _settings_trail(
        db, actor=actor, what="reason_added", detail={"label": reason.label}, now=now
    )
    return reason


def rename_reason(
    db: Session, *, actor: User, reason: LostReason, label: str, now: datetime
) -> LostReason:
    before = reason.label
    reason.label = label.strip()
    db.flush()
    _settings_trail(
        db,
        actor=actor,
        what="reason_renamed",
        detail={"from": before, "to": reason.label},
        now=now,
    )
    return reason


def archive_reason(
    db: Session, *, actor: User, reason: LostReason, now: datetime
) -> LostReason:
    reason.archived_at = now
    db.flush()
    _settings_trail(
        db, actor=actor, what="reason_archived", detail={"label": reason.label}, now=now
    )
    return reason


def restore_reason(
    db: Session, *, actor: User, reason: LostReason, now: datetime
) -> LostReason:
    reason.archived_at = None
    db.flush()
    _settings_trail(
        db, actor=actor, what="reason_restored", detail={"label": reason.label}, now=now
    )
    return reason


def add_segment(
    db: Session, *, actor: User, plan: Any, days: int, now: datetime
) -> SalesSegment:
    segment = db.scalars(
        select(SalesSegment).where(
            SalesSegment.plan_id == plan.id, SalesSegment.days == days
        )
    ).first()
    if segment is None:
        segment = SalesSegment(plan_id=plan.id, days=days, created_by_id=actor.id)
        db.add(segment)
        db.flush()
    _settings_trail(
        db,
        actor=actor,
        what="segment_added",
        detail={"plan": plan.code, "days": days},
        now=now,
    )
    return segment


def remove_segment(
    db: Session, *, actor: User, segment: SalesSegment, now: datetime
) -> None:
    detail = {"plan": segment.plan.code, "days": segment.days}
    db.delete(segment)
    db.flush()
    _settings_trail(db, actor=actor, what="segment_removed", detail=detail, now=now)


def note_viewed(db: Session, *, client: User, actor: User) -> None:
    from app.modules.backoffice.services import seen

    seen(db, customer=client, actor=actor, kind=ActionKind.SALES_VIEW)


__all__ = [
    "add_note",
    "add_reason",
    "add_segment",
    "adopt_arizas",
    "archive_reason",
    "claim_client",
    "close_as_lost",
    "close_months",
    "credit_sale",
    "lift_hold",
    "lift_on_payment",
    "mark_awaiting",
    "mark_callback",
    "mark_thinking",
    "mark_using",
    "move_to_taken",
    "note_viewed",
    "record_no_answer",
    "release_expired",
    "remove_segment",
    "rename_reason",
    "reopen_card",
    "restore_reason",
    "return_to_pool",
    "set_ending_days",
    "set_rule",
]
