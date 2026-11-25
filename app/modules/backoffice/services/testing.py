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
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
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
from app.common.crypto import decrypt, encrypt
from app.common.exceptions import DecryptionFailed, DomainError
from app.common.money import decimal_places
from app.modules.accounts.models import User
from app.modules.autopay.exceptions import AutopayUnavailable, PhoneRequired
from app.modules.autopay.models import SavedCard
from app.modules.autopay.selectors import active_card
from app.modules.autopay.services import _token, cards, phone_of
from app.modules.billing.models import TestCard, TestPayment
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
CARD_PENDING: Final = "pending"
CARD_ACTIVE: Final = "active"
CARD_REVOKED: Final = "revoked"
# Multicard's card page lives 15 minutes; read a pending one back a while longer.
BIND_PAGE_SECONDS: Final = 30 * 60


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
    db: Session,
    *,
    actor: User,
    method: str,
    usd_cents: int,
    now: datetime,
    card_id: str = "",
) -> TestPayment:
    """A trial payment; ``card`` takes it from a test card bound here
    (``card_id``) or, with none named, from the account's own card."""
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
    token = ""
    if method == CARD and card_id:
        test_card = _test_card(db, actor=actor, card_id=card_id)
        token = _decrypted(test_card.token_encrypted)
        if test_card.status != CARD_ACTIVE or not token:
            raise TestingRefused("Bu test karta ulanmagan.")
        row.card_id = test_card.id
        row.card_pan = test_card.pan[:32]
        row.card_ps = test_card.ps[:16]
    elif method == CARD:
        token, card = _card_of(db, actor)
        row.card_pan = card.pan[:32]
        row.card_ps = card.ps[:16]
    db.add(row)
    # Written before Multicard is asked: its callback reads this row.
    db.commit()
    if method == PAGE:
        return _open_page(db, row)
    return _charge(db, row, token)


def _decrypted(blob: bytes | None) -> str:
    if not blob:
        return ""
    try:
        return decrypt(blob)
    except DecryptionFailed:
        return ""


def _card_of(db: Session, actor: User) -> tuple[str, SavedCard]:
    card = active_card(db, owner=actor)
    token = _token(card) if card is not None else ""
    if card is None or not token:
        raise TestingRefused(
            "Sizning akkauntingizda ulangan karta yo'q - bu yerda test karta "
            "ulang yoki «To'lov sahifasi» usulini tanlang."
        )
    return token, card


# --- Test cards: bound here, apart from the account's own card ------------


def _test_card(db: Session, *, actor: User, card_id: object) -> TestCard:
    try:
        key = uuid.UUID(str(card_id))
    except ValueError as exc:
        raise TestingRefused("Test karta topilmadi.") from exc
    card = db.scalar(
        select(TestCard).where(TestCard.id == key, TestCard.actor_id == actor.id)
    )
    if card is None:
        raise TestingRefused("Test karta topilmadi.")
    return card


def start_card_binding(
    db: Session, *, actor: User, phone: str, now: datetime
) -> tuple[TestCard, str]:
    """Multicard's card page for a test card; answers the card and the page."""
    try:
        adapter = cards()
    except AutopayUnavailable as exc:
        raise TestingRefused("Karta ulash bu serverda yoqilmagan.") from exc
    # No phone given: none is sent (Multicard needs it for Humo only).
    number = ""
    if phone.strip():
        try:
            number = phone_of(phone, user=actor)
        except PhoneRequired as exc:
            raise TestingRefused(
                "Telefon raqami 998 va 9 ta raqam bo'lsin (karta SMS keladigan raqam)."
            ) from exc
    back = f"{settings.site_url}/ofis/test/"
    try:
        session = adapter.start_card_binding(
            phone=number,
            redirect_url=f"{back}?card=bound",
            decline_url=f"{back}?card=declined",
            callback_url=settings.multicard_card_callback_url,
        )
    except PaymentError as exc:
        raise TestingRefused(f"Rahmat karta sahifasini ochmadi: {exc}") from exc
    card = TestCard(
        actor_id=actor.id, session_id=session.session_id, status=CARD_PENDING
    )
    db.add(card)
    db.commit()
    return card, session.form_url


def finish_card(db: Session, *, card: TestCard, now: datetime) -> TestCard:
    """Ask Multicard which card its page added; keep it if one was."""
    if card.status != CARD_PENDING:
        return card
    try:
        bound = cards().bound_card(session_id=card.session_id)
    except (PaymentError, AutopayUnavailable) as exc:
        logger.warning("test card %s could not be read: %s", card.session_id, exc)
        return card
    if bound is None or not bound.usable:
        return card
    card.status = CARD_ACTIVE
    card.token_encrypted = encrypt(bound.token)
    card.pan = bound.pan[:32]
    card.ps = bound.ps[:16]
    card.holder = bound.holder[:100]
    card.bound_at = now
    db.flush()
    logger.info("test card %s bound for %s", card.pan, card.actor_id)
    return card


def card_reported(db: Session, *, session_id: str, now: datetime) -> bool:
    """Multicard's card callback, for a session that is no account's card."""
    card = db.scalar(select(TestCard).where(TestCard.session_id == session_id))
    if card is None:
        return False
    finish_card(db, card=card, now=now)
    return True


def bound_test_cards(db: Session, *, actor: User, now: datetime) -> list[TestCard]:
    """The actor's test cards, a page still open read once more."""
    rows = list(
        db.scalars(
            select(TestCard)
            .where(
                TestCard.actor_id == actor.id,
                TestCard.status.in_((CARD_PENDING, CARD_ACTIVE)),
            )
            .order_by(TestCard.created_at.desc())
        )
    )
    fresh = now - timedelta(seconds=BIND_PAGE_SECONDS)
    for card in rows:
        if card.status == CARD_PENDING and card.created_at >= fresh:
            finish_card(db, card=card, now=now)
    db.commit()
    return [card for card in rows if card.status == CARD_ACTIVE]


def remove_test_card(
    db: Session, *, actor: User, card_id: object, now: datetime
) -> None:
    card = _test_card(db, actor=actor, card_id=card_id)
    token = _decrypted(card.token_encrypted)
    card.status = CARD_REVOKED
    card.revoked_at = now
    card.token_encrypted = None
    db.commit()
    if not token:
        return
    try:
        cards().revoke_card(token=token)
    except (PaymentError, DomainError) as exc:
        logger.warning("test card %s could not be voided: %s", card.id, exc)


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
