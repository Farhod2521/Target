"""«Testing»: the superuser pays a dollar's worth to try a card, for real.

Rahmat takes so'm only, so the dollars asked for are turned into so'm at
the Central Bank's rate of the day and that is charged; a Visa or
Mastercard abroad is debited in its own currency by its bank. Nothing is
bought: the payment's ``TEST-`` number is no bill, its callback is answered
by :mod:`app.modules.billing.services.test_payments`, and the money stays
until the superuser returns it here.

Two ways: ``card`` charges the superuser's own saved card, as autopay
does; ``page`` opens Multicard's checkout page, where any card is typed.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from typing import Final

from paykit import (
    CheckoutRequest,
    InvoiceNumber,
    MinorUnits,
    PaymentError,
    ProviderName,
    ProviderNotRegistered,
    RefundPort,
    registry,
)
from paykit.multicard import PROVIDER as MULTICARD
from paykit.multicard import MulticardAdapter
from paykit.multicard.cards import CHARGED, DECLINED, NEEDS_CODE, PENDING, WRONG_CODE
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.exceptions import DomainError
from app.common.money import decimal_places
from app.modules.accounts.models import User
from app.modules.autopay.exceptions import AutopayUnavailable
from app.modules.autopay.selectors import active_card
from app.modules.autopay.services import _token, cards
from app.modules.billing.models import TestPayment
from app.modules.billing.selectors.display import usd_rate
from app.modules.billing.services import test_payments as states

logger = logging.getLogger(__name__)

CARD: Final = "card"
PAGE: Final = "page"
METHODS: Final = (CARD, PAGE)
# A code awaited: Multicard texted one and gave no page to confirm on.
CODE: Final = "code"
MAX_USD_CENTS: Final = 10_000
PAGE_TTL_SECONDS: Final = 30 * 60
UZS: Final = "UZS"
DESCRIPTION: Final = "TargetologAI test to'lovi"


class TestingRefused(DomainError):
    __test__ = False


@dataclass(frozen=True, slots=True)
class Rate:
    uzs_per_usd: Decimal
    date: str


def current_rate() -> Rate | None:
    found = usd_rate()
    if found is None or found[0] <= 0:
        return None
    return Rate(uzs_per_usd=found[0], date=found[1])


def _rate() -> Rate:
    rate = current_rate()
    if rate is None:
        raise TestingRefused("Dollar kursi topilmadi - birozdan keyin urinib ko'ring.")
    return rate


def in_uzs(usd_cents: int, rate: Rate) -> int:
    """Whole so'm for these cents, rounded up so the card pays no less."""
    som = Decimal(usd_cents) / 100 * rate.uzs_per_usd
    return int(som.to_integral_value(rounding=ROUND_CEILING))


def _places() -> int:
    return decimal_places(UZS)


def _live() -> MulticardAdapter:
    """The live Rahmat shop - never the sandbox: this is about real cards."""
    try:
        adapter = registry.get(ProviderName(MULTICARD))
    except ProviderNotRegistered as exc:
        raise TestingRefused("Rahmat bu serverda sozlanmagan.") from exc
    if not isinstance(adapter, MulticardAdapter):
        raise TestingRefused("Rahmat bu serverda sozlanmagan.")
    return adapter


def start(
    db: Session, *, actor: User, method: str, usd_cents: int, now: datetime
) -> TestPayment:
    if method not in METHODS:
        raise TestingRefused("To'lov usuli noto'g'ri.")
    if usd_cents < 1 or usd_cents > MAX_USD_CENTS:
        raise TestingRefused("Summa 0,01 dan 100 dollargacha bo'lsin.")
    rate = _rate()
    row = TestPayment(
        number=states.new_number(),
        actor_id=actor.id,
        method=method,
        usd_cents=usd_cents,
        amount_uzs=in_uzs(usd_cents, rate),
        rate=str(rate.uzs_per_usd),
        rate_date=rate.date,
        status=states.CREATED,
    )
    if method == CARD:
        token, card = _card_of(db, actor)
        row.card_pan = card.pan[:32]
        row.card_ps = card.ps[:16]
    db.add(row)
    # Written before Multicard is asked: its callback reads this row.
    db.commit()
    if method == PAGE:
        return _open_page(db, row)
    return _charge(db, row, token)


def _card_of(db: Session, actor: User):  # type: ignore[no-untyped-def]
    card = active_card(db, owner=actor)
    token = _token(card) if card is not None else ""
    if card is None or not token:
        raise TestingRefused(
            "Sizning akkauntingizda ulangan karta yo'q - kabinetda karta ulang "
            "yoki «To'lov sahifasi» usulini tanlang."
        )
    return token, card


def _open_page(db: Session, row: TestPayment) -> TestPayment:
    try:
        page = _live().checkout(
            request=CheckoutRequest(
                number=InvoiceNumber(row.number),
                amount_minor=MinorUnits(row.amount_uzs * 10 ** _places()),
                decimal_places=_places(),
                currency=UZS,
                description=DESCRIPTION,
                return_url=f"{settings.site_url}/ofis/test/",
                ttl_seconds=PAGE_TTL_SECONDS,
            )
        )
    except PaymentError as exc:
        return _failed(db, row, f"Rahmat sahifa ochmadi: {exc}")
    row.status = states.WAITING
    row.page_url = page.url[:512]
    row.raw = {**(row.raw or {}), "invoice_uuid": page.reference}
    db.commit()
    return row


def _charge(db: Session, row: TestPayment, token: str) -> TestPayment:
    try:
        adapter = cards()
    except AutopayUnavailable:
        return _failed(db, row, "Kartadan to'lov bu serverda yoqilmagan.")
    try:
        charge = adapter.charge_card(
            token=token,
            number=row.number,
            amount_minor=row.amount_uzs * 10 ** _places(),
            decimal_places=_places(),
            currency=UZS,
            description=DESCRIPTION,
        )
    except PaymentError as exc:
        return _failed(db, row, f"Rahmat javob bermadi: {exc}")
    logger.info("test payment %s: %s %s", row.number, charge.outcome, charge.code)
    db.refresh(row)
    _apply(
        row,
        outcome=charge.outcome,
        uuid=charge.uuid,
        code=charge.code,
        details=charge.details,
    )
    if charge.outcome == NEEDS_CODE:
        row.page_url = (charge.checkout_url or "")[:512]
        row.status = states.WAITING if charge.checkout_url else CODE
    db.commit()
    return row


def _apply(
    row: TestPayment, *, outcome: str, uuid: str, code: str, details: str
) -> None:
    if uuid:
        row.external_id = uuid
    if row.status in (states.PAID, states.REFUNDED):
        return  # the callback came first and said more
    if outcome == CHARGED:
        row.status = states.PAID
    elif outcome == PENDING:
        row.status = states.WAITING
    elif outcome == DECLINED:
        row.status = states.FAILED
        row.detail = " ".join(part for part in (code, details) if part)[:255]


def _failed(db: Session, row: TestPayment, detail: str) -> TestPayment:
    row.status = states.FAILED
    row.detail = detail[:255]
    db.commit()
    return row


def _mine(db: Session, *, actor: User, payment_id: object) -> TestPayment:
    row = db.scalar(
        select(TestPayment).where(
            TestPayment.id == payment_id, TestPayment.actor_id == actor.id
        )
    )
    # No row lock: Multicard's PUT waits for our callback, which locks it.
    if row is None:
        raise TestingRefused("Test to'lov topilmadi.")
    return row


def confirm(db: Session, *, actor: User, payment_id: object, code: str) -> TestPayment:
    """The SMS code Multicard texted for a card charge."""
    row = _mine(db, actor=actor, payment_id=payment_id)
    if row.status != CODE or not row.external_id:
        raise TestingRefused("Bu to'lov kod kutmayapti.")
    digits = "".join(ch for ch in code if ch.isdigit())
    if not digits:
        raise TestingRefused("Kodni kiriting.")
    try:
        charge = cards().confirm_charge(uuid=row.external_id, code=digits)
    except (PaymentError, AutopayUnavailable) as exc:
        raise TestingRefused(f"Rahmat javob bermadi: {exc}") from exc
    db.refresh(row)
    if charge.outcome == DECLINED and charge.code == WRONG_CODE:
        db.commit()
        raise TestingRefused("Kod noto'g'ri.")
    _apply(
        row, outcome=charge.outcome, uuid="", code=charge.code, details=charge.details
    )
    db.commit()
    return row


def check(db: Session, *, actor: User, payment_id: object) -> TestPayment:
    """Multicard asked again how a payment stands."""
    row = _mine(db, actor=actor, payment_id=payment_id)
    if not row.external_id:
        return row
    try:
        charge = _live().charge_status(uuid=row.external_id)
    except PaymentError as exc:
        raise TestingRefused(f"Rahmat javob bermadi: {exc}") from exc
    if charge.status == "revert":
        row.status = states.REFUNDED
    else:
        _apply(
            row,
            outcome=charge.outcome,
            uuid="",
            code=charge.code,
            details=charge.details,
        )
    db.commit()
    return row


def refund(
    db: Session, *, actor: User, payment_id: object, now: datetime
) -> TestPayment:
    """The whole payment back to the card it came from."""
    row = _mine(db, actor=actor, payment_id=payment_id)
    if row.status == states.REFUNDED:
        return row
    if row.status != states.PAID or not row.external_id:
        raise TestingRefused("Faqat to'langan test to'lovni qaytarish mumkin.")
    adapter = _live()
    if not isinstance(adapter, RefundPort):
        raise TestingRefused("Rahmat pulni qaytarishni qo'llamaydi.")
    try:
        adapter.refund(external_id=row.external_id)
    except PaymentError as exc:
        raise TestingRefused(f"Rahmat pulni qaytarmadi: {exc}") from exc
    row.status = states.REFUNDED
    row.refunded_at = now
    db.commit()
    logger.info("test payment %s refunded by %s", row.number, actor.id)
    return row


def recent(db: Session, *, limit: int = 50) -> list[TestPayment]:
    return list(
        db.scalars(
            select(TestPayment).order_by(TestPayment.created_at.desc()).limit(limit)
        )
    )
