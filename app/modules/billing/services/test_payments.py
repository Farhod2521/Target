"""The office's trial payments, as Multicard's callbacks report them.

A trial payment pays for nothing: its ``TEST-`` number is no bill, so the
ordinary handlers would refuse it - and Multicard returns a refused payment
to the card. Here a signed callback for one is answered ``success`` and the
row is marked paid, so the money stays until the superuser returns it.
"""

import logging
import secrets
from datetime import datetime
from typing import Final

from paykit import (
    AMOUNT_MISMATCH,
    CANCEL,
    INVOICE_NOT_FOUND,
    PERFORM,
    STATE_NOT_ALLOWED,
    STATUS,
    CallbackRequest,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    Outcome,
    RefundPort,
    Refused,
    Settled,
    TransactionRecord,
    registry,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.money import decimal_places
from app.modules.billing.models import TestPayment

logger = logging.getLogger(__name__)

PREFIX: Final = "TEST-"
CREATED: Final = "created"
WAITING: Final = "waiting"
PAID: Final = "paid"
FAILED: Final = "failed"
REFUNDED: Final = "refunded"


def new_number() -> str:
    return PREFIX + secrets.token_hex(5).upper()


def is_test(number: str | None) -> bool:
    return bool(number) and str(number).startswith(PREFIX)


def amount_minor(row: TestPayment) -> int:
    """The row's so'm in the minor units Multicard's adapter reads back."""
    return row.amount_uzs * 10 ** decimal_places(settings.billing_currency)


def _locked(db: Session, number: str) -> TestPayment | None:
    return db.scalar(
        select(TestPayment).where(TestPayment.number == number).with_for_update()
    )


def _record(row: TestPayment, request: CallbackRequest) -> TransactionRecord:
    return TransactionRecord(
        number=InvoiceNumber(row.number),
        reference=row.number,
        external_id=ExternalId(row.external_id or request.external_id or ""),
        state="performed",
        amount_minor=MinorUnits(amount_minor(row)),
        created_at=row.created_at,
        performed_at=row.paid_at,
    )


def on_callback(db: Session, *, request: CallbackRequest, now: datetime) -> Outcome:
    """One signed Multicard callback or status webhook about a trial payment."""
    row = _locked(db, str(request.number))
    if row is None or request.command not in (PERFORM, STATUS, CANCEL):
        return Refused(reason=INVOICE_NOT_FOUND)
    raw = dict(request.raw)
    if request.command == PERFORM:
        if request.amount_minor != amount_minor(row):
            return Refused(reason=AMOUNT_MISMATCH, detail=str(request.amount_minor))
        if row.status == REFUNDED:
            return Refused(reason=STATE_NOT_ALLOWED, detail=row.status)
        if row.status != PAID:
            row.status = PAID
            row.paid_at = now
            row.detail = ""
        row.external_id = str(request.external_id or row.external_id)
        row.card_pan = str(raw.get("card_pan") or row.card_pan)[:32]
        row.card_ps = str(raw.get("ps") or row.card_ps)[:16]
        row.raw = {**(row.raw or {}), "callback": raw}
        db.flush()
        logger.info("test payment %s paid", row.number)
        return Settled(transaction=_record(row, request))
    if request.command == CANCEL and _reverted(request):
        row.status = REFUNDED
        row.refunded_at = row.refunded_at or now
    row.raw = {**(row.raw or {}), "webhook": raw}
    db.flush()
    return Settled(transaction=_record(row, request))


def _reverted(request: CallbackRequest) -> bool:
    """A revert webhook's signature leaves its status out: read it back."""
    adapter = registry.get(request.provider)
    if not isinstance(adapter, RefundPort) or not request.external_id:
        return False
    try:
        return adapter.reverted(external_id=str(request.external_id))
    except Exception as exc:
        logger.warning("test payment revert not read back: %s", exc)
        return False
