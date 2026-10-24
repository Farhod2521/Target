"""What the payment providers ask us: check, hold, perform, cancel, report."""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from paykit import (
    CANCEL,
    CHECK,
    CREATE,
    INVOICE_HELD,
    INVOICE_NOT_FOUND,
    INVOICE_NOT_PAYABLE,
    MALFORMED,
    PERFORM,
    STATE_NOT_ALLOWED,
    STATEMENT,
    STATUS,
    TIMED_OUT,
    TRANSACTION_NOT_FOUND,
    CallbackRequest,
    Command,
    MalformedCallback,
    Outcome,
    ProviderResponse,
    RawRequest,
    Refused,
    Settled,
    Statement,
    registry,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import ConfigurationError
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.constants import (
    NUMBER_ATTEMPTS,
    TRANSACTION_TTL_HOURS,
    HistoryKind,
    InvoiceStatus,
    SubscriptionStatus,
    TransactionState,
)
from app.modules.billing.exceptions import NothingHeld
from app.modules.billing.models import Invoice, PaymentTransaction, Subscription
from app.modules.billing.selectors import (
    held_transactions,
    locked_attempt,
    locked_invoice,
    record_of,
    transaction_by_external,
    transactions_in_window,
)
from app.modules.billing.services.entitlement import (
    new_transaction_reference,
    payer,
    record_change,
)
from app.modules.billing.services.invoices import (
    apply_payment,
    check_invoice,
    payability_refusal,
)

logger = logging.getLogger(__name__)
Handler = Callable[..., Outcome]


def record_attempt(
    db: Session,
    *,
    invoice: Invoice,
    request: CallbackRequest,
    state: TransactionState,
    now: datetime,
) -> PaymentTransaction:
    for _attempt in range(NUMBER_ATTEMPTS):
        attempt = PaymentTransaction(
            owner_id=payer(invoice).id,
            invoice_id=invoice.id,
            provider=request.provider,
            external_id=request.external_id or "",
            reference=new_transaction_reference(),
            state=state,
            amount_minor=invoice.amount_minor,
            currency=invoice.currency,
            requested_at=request.requested_at,
            performed_at=now if state == TransactionState.PERFORMED else None,
            raw=dict(request.raw),
        )
        try:
            with db.begin_nested():
                db.add(attempt)
        except IntegrityError:
            continue
        db.refresh(attempt)
        return attempt
    raise ConfigurationError("transaction reference generator produced only collisions")


def release_hold(
    db: Session,
    *,
    attempt: PaymentTransaction,
    reason: int | None,
    now: datetime,
    raw: Mapping[str, Any] | None = None,
) -> None:
    attempt.state = TransactionState.CANCELED
    attempt.canceled_at = now
    attempt.cancel_reason = reason
    if raw is not None:
        attempt.raw = dict(raw)
    invoice = attempt.invoice
    if invoice.status == InvoiceStatus.HELD:
        invoice.status = (
            InvoiceStatus.EXPIRED
            if invoice.expires_at <= now
            else InvoiceStatus.PENDING
        )
    db.flush()


def hold_invoice(db: Session, *, request: CallbackRequest, now: datetime) -> Outcome:
    if not request.external_id:
        return Refused(reason=MALFORMED, detail="no transaction id")
    invoice = locked_invoice(db, number=request.number or "")
    if invoice is None:
        return Refused(reason=INVOICE_NOT_FOUND)
    existing = transaction_by_external(
        db, provider=request.provider, external_id=request.external_id
    )
    if existing is not None:
        if existing.state == TransactionState.CREATED:
            return Settled(transaction=record_of(existing))
        return Refused(reason=STATE_NOT_ALLOWED, detail=existing.state)
    refusal = payability_refusal(
        invoice=invoice, amount_minor=request.amount_minor, now=now
    )
    if refusal == INVOICE_NOT_PAYABLE and invoice.status == InvoiceStatus.HELD:
        refusal = INVOICE_HELD
    if refusal is not None:
        return Refused(reason=refusal, detail=invoice.status)
    attempt = record_attempt(
        db, invoice=invoice, request=request, state=TransactionState.CREATED, now=now
    )
    invoice.status = InvoiceStatus.HELD
    db.flush()
    return Settled(transaction=record_of(attempt))


def settle_invoice(db: Session, *, request: CallbackRequest, now: datetime) -> Outcome:
    attempt = (
        locked_attempt(db, provider=request.provider, external_id=request.external_id)
        if request.external_id
        else None
    )
    if attempt is None:
        if request.number is None:
            return Refused(reason=TRANSACTION_NOT_FOUND)
        invoice = locked_invoice(db, number=request.number)
        if invoice is None:
            return Refused(reason=INVOICE_NOT_FOUND)
        refusal = payability_refusal(
            invoice=invoice, amount_minor=request.amount_minor, now=now
        )
        if refusal is not None:
            return Refused(reason=refusal, detail=invoice.status)
        attempt = record_attempt(
            db,
            invoice=invoice,
            request=request,
            state=TransactionState.PERFORMED,
            now=now,
        )
        apply_payment(db, invoice=invoice, now=now)
        return Settled(transaction=record_of(attempt))
    if attempt.state == TransactionState.PERFORMED:
        return Settled(transaction=record_of(attempt))
    if attempt.state != TransactionState.CREATED:
        return Refused(reason=STATE_NOT_ALLOWED, detail=attempt.state)
    if attempt.created_at + timedelta(hours=TRANSACTION_TTL_HOURS) <= now:
        release_hold(db, attempt=attempt, reason=None, now=now)
        return Refused(reason=TIMED_OUT, detail=attempt.reference)
    attempt.state = TransactionState.PERFORMED
    attempt.performed_at = now
    attempt.raw = dict(request.raw)
    db.flush()
    apply_payment(db, invoice=attempt.invoice, now=now)
    return Settled(transaction=record_of(attempt))


def revoke_payment(db: Session, *, invoice: Invoice, now: datetime) -> None:
    invoice.status = InvoiceStatus.REFUNDED
    invoice.canceled_at = now
    db.flush()
    if invoice.owner_id is None:
        return
    emit(
        db,
        owner_id=invoice.owner_id,
        name=EventName.PAYMENT_REFUNDED,
        aggregate_type="invoice",
        aggregate_id=invoice.id,
        payload={
            "number": invoice.number,
            "plan": invoice.plan.code,
            "amount_minor": invoice.amount_minor,
            "currency": invoice.currency,
            "days": invoice.applied_days,
        },
        occurred_at=now,
    )
    if invoice.subscription_id is None or invoice.applied_days <= 0:
        return
    subscription = db.get(Subscription, invoice.subscription_id, with_for_update=True)
    if subscription is None:
        return
    before = subscription.expires_at
    subscription.expires_at -= timedelta(days=invoice.applied_days)
    ended = subscription.expires_at <= now
    if ended:
        subscription.status = SubscriptionStatus.EXPIRED
        subscription.ended_at = now
    db.flush()
    record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.REFUNDED,
        from_plan=subscription.plan,
        move=None,
        days=-invoice.applied_days,
        expires_before=before,
        now=now,
        invoice=invoice,
    )
    emit(
        db,
        owner_id=invoice.owner_id,
        name=EventName.SUBSCRIPTION_SHORTENED,
        aggregate_type="subscription",
        aggregate_id=subscription.id,
        payload={
            "expires_at": subscription.expires_at.isoformat(),
            "days_removed": invoice.applied_days,
            "invoice": invoice.number,
            "ended": ended,
        },
        occurred_at=now,
    )


def void_transaction(
    db: Session, *, request: CallbackRequest, now: datetime
) -> Outcome:
    attempt = (
        locked_attempt(db, provider=request.provider, external_id=request.external_id)
        if request.external_id
        else None
    )
    if attempt is None:
        return Refused(reason=TRANSACTION_NOT_FOUND)
    if attempt.state in (TransactionState.CANCELED, TransactionState.REFUNDED):
        return Settled(transaction=record_of(attempt))
    if attempt.state == TransactionState.CREATED:
        release_hold(
            db, attempt=attempt, reason=request.cancel_reason, now=now, raw=request.raw
        )
        return Settled(transaction=record_of(attempt))
    attempt.state = TransactionState.REFUNDED
    attempt.canceled_at = now
    attempt.cancel_reason = request.cancel_reason
    attempt.raw = dict(request.raw)
    db.flush()
    revoke_payment(db, invoice=attempt.invoice, now=now)
    return Settled(transaction=record_of(attempt))


def _read_transaction(
    db: Session, *, request: CallbackRequest, now: datetime
) -> Outcome:
    attempt = transaction_by_external(
        db, provider=request.provider, external_id=request.external_id or ""
    )
    if attempt is None:
        return Refused(reason=TRANSACTION_NOT_FOUND)
    return Settled(transaction=record_of(attempt))


def _read_statement(db: Session, *, request: CallbackRequest, now: datetime) -> Outcome:
    if request.window_start is None or request.window_end is None:
        return Refused(reason=MALFORMED, detail="no window")
    rows = transactions_in_window(
        db,
        provider=request.provider,
        start=request.window_start,
        end=request.window_end,
    )
    return Statement(transactions=[record_of(row) for row in rows])


HANDLERS: dict[Command, Handler] = {
    CHECK: check_invoice,
    CREATE: hold_invoice,
    PERFORM: settle_invoice,
    CANCEL: void_transaction,
    STATUS: _read_transaction,
    STATEMENT: _read_statement,
}


def handle_callback(
    db: Session,
    *,
    provider: str,
    headers: Mapping[str, str],
    body: bytes,
    form: Mapping[str, str],
    now: datetime,
) -> ProviderResponse:
    adapter = registry.get(provider)
    raw = RawRequest(headers=headers, body=body, form=form)
    if not adapter.authenticate(request=raw):
        logger.warning(
            "payment callback failed authentication", extra={"provider": provider}
        )
        return adapter.refuse_unauthenticated(request=raw)
    try:
        request = adapter.parse(request=raw)
    except MalformedCallback as exc:
        logger.warning(
            "payment callback could not be read",
            extra={"provider": provider, "reason": str(exc)},
        )
        return adapter.refuse_malformed(request=raw)
    handler = HANDLERS.get(request.command)
    outcome: Outcome
    if handler is None:
        outcome = Refused(reason=MALFORMED, detail=request.command)
    else:
        try:
            outcome = handler(db, request=request, now=now)
            db.commit()
        except Exception:
            db.rollback()
            raise
    if isinstance(outcome, Refused):
        logger.info(
            "payment callback refused",
            extra={
                "provider": provider,
                "command": request.command,
                "reason": outcome.reason,
                "detail": outcome.detail,
            },
        )
    return adapter.render(request=request, outcome=outcome)


def release_stale_holds(db: Session, *, now: datetime) -> int:
    cutoff = now - timedelta(hours=TRANSACTION_TTL_HOURS)
    stale = [
        (row.provider, row.external_id) for row in held_transactions(db, cutoff=cutoff)
    ]
    released = 0
    for provider, external_id in stale:
        attempt = locked_attempt(db, provider=provider, external_id=external_id)
        if attempt is None or attempt.state != TransactionState.CREATED:
            db.rollback()
            continue
        release_hold(db, attempt=attempt, reason=None, now=now)
        db.commit()
        released += 1
    if released:
        logger.info("released abandoned payment holds", extra={"count": released})
    return released


def abandon_hold(
    db: Session, *, provider: str, external_id: str, actor: User, now: datetime
) -> PaymentTransaction:
    attempt = locked_attempt(db, provider=provider, external_id=external_id)
    if attempt is None or attempt.state != TransactionState.CREATED:
        raise NothingHeld
    release_hold(db, attempt=attempt, reason=None, now=now)
    logger.info(
        "payment hold released by hand",
        extra={
            "provider": provider,
            "external_id": external_id,
            "invoice": attempt.invoice.number,
            "actor_id": str(actor.id),
        },
    )
    return attempt
