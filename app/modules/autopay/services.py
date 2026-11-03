"""Binding a card at Multicard, and renewing a paid plan from it."""

import logging
from dataclasses import dataclass
from datetime import datetime

from paykit import PaymentError, ProviderName, ProviderNotRegistered, registry
from paykit.multicard import (
    CHARGED,
    DECLINED,
    NEEDS_CODE,
    PENDING,
    Charge,
    MulticardAdapter,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.crypto import decrypt, encrypt, fingerprint
from app.common.exceptions import DecryptionFailed, DomainError
from app.common.money import decimal_places
from app.modules.accounts.models import User
from app.modules.autopay.constants import (
    CARD_DECLINED_PATH,
    CARD_DONE_PATH,
    CHARGE_ERROR_MAX,
    CHARGE_ERRORS,
    MAX_ATTEMPTS,
    PHONE_DIGITS,
    PHONE_PREFIX,
    PROVIDER,
    RETRY_GAP,
    CardStatus,
)
from app.modules.autopay.exceptions import (
    AutopayUnavailable,
    CardNotFound,
    CardServiceDown,
    ConsentRequired,
    PhoneRequired,
)
from app.modules.autopay.models import SavedCard
from app.modules.autopay.selectors import (
    active_card,
    card_by_session,
    due_card_ids,
    pending_card,
    renewing_subscription,
)
from app.modules.billing.models import Invoice, Subscription
from app.modules.billing.services import create_invoice

logger = logging.getLogger(__name__)


def autopay_on() -> bool:
    return bool(
        settings.multicard_autopay_enabled and settings.multicard_card_callback_url
    )


def cards() -> MulticardAdapter:
    """Rahmat's adapter, when autopay is switched on and Rahmat is configured."""
    if not autopay_on():
        raise AutopayUnavailable
    try:
        adapter = registry.get(ProviderName(PROVIDER))
    except ProviderNotRegistered as exc:
        raise AutopayUnavailable from exc
    if not isinstance(adapter, MulticardAdapter):
        raise AutopayUnavailable
    return adapter


def phone_of(given: str, *, user: User) -> str:
    """The card owner's phone as Multicard takes it: 998 and nine digits."""
    digits = "".join(ch for ch in (given or user.phone or "") if ch.isdigit())
    if len(digits) == PHONE_DIGITS - len(PHONE_PREFIX):
        digits = PHONE_PREFIX + digits
    if len(digits) != PHONE_DIGITS or not digits.startswith(PHONE_PREFIX):
        raise PhoneRequired
    return digits


# --- Binding --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Binding:
    session_id: str
    form_url: str


def start_binding(
    db: Session, *, user: User, phone: str, consent: bool, now: datetime
) -> Binding:
    """A Multicard page where the owner adds the card the plan is renewed from."""
    if not consent:
        raise ConsentRequired
    adapter = cards()
    number = phone_of(phone, user=user)
    try:
        session = adapter.start_card_binding(
            phone=number,
            redirect_url=settings.site_url + CARD_DONE_PATH,
            decline_url=settings.site_url + CARD_DECLINED_PATH,
            callback_url=settings.multicard_card_callback_url,
        )
    except PaymentError as exc:
        logger.warning("card page could not be opened: %s", exc)
        raise CardServiceDown from exc
    db.add(
        SavedCard(
            owner_id=user.id,
            provider=PROVIDER,
            session_id=session.session_id,
            status=CardStatus.PENDING,
            consented_at=now,
        )
    )
    db.flush()
    return Binding(session_id=session.session_id, form_url=session.form_url)


def finish_binding(db: Session, *, card: SavedCard, now: datetime) -> SavedCard:
    """Ask Multicard which card its page added; keep it if one was.

    The page's callback is not signed, so it only says *when* to ask: the
    card itself is read from Multicard by its session.
    """
    if card.status != CardStatus.PENDING:
        return card
    try:
        bound = cards().bound_card(session_id=card.session_id)
    except PaymentError as exc:
        logger.warning("card binding %s could not be read: %s", card.session_id, exc)
        raise CardServiceDown from exc
    if bound is None or not bound.usable:
        return card
    previous = db.scalar(
        select(SavedCard)
        .where(
            SavedCard.owner_id == card.owner_id,
            SavedCard.status == CardStatus.ACTIVE,
            SavedCard.id != card.id,
        )
        .with_for_update()
    )
    if previous is not None:
        _revoke(previous, now=now)
        db.flush()
    card.status = CardStatus.ACTIVE
    card.token_encrypted = encrypt(bound.token)
    card.token_fingerprint = fingerprint(bound.token)
    card.pan = bound.pan[:32]
    card.ps = bound.ps[:16]
    card.holder = bound.holder[:100]
    card.bound_at = now
    card.autopay = True
    db.flush()
    logger.info("card %s bound for owner %s", card.pan, card.owner_id)
    return card


def binding_reported(db: Session, *, session_id: str, now: datetime) -> bool:
    """Multicard's callback for a binding page: read the card it names."""
    card = card_by_session(db, session_id=session_id)
    if card is None:
        logger.warning("card callback for an unknown session %s", session_id)
        return False
    finish_binding(db, card=card, now=now)
    return True


def check_binding(
    db: Session, *, user: User, session_id: str, now: datetime
) -> SavedCard:
    card = pending_card(db, owner=user, session_id=session_id)
    if card is None:
        raise CardNotFound
    return finish_binding(db, card=card, now=now)


def set_autopay(db: Session, *, user: User, enabled: bool) -> SavedCard:
    card = active_card(db, owner=user)
    if card is None:
        raise CardNotFound
    card.autopay = enabled
    db.flush()
    return card


def remove_card(db: Session, *, user: User, now: datetime) -> None:
    """Forget the card here and ask Multicard to void its token."""
    card = active_card(db, owner=user)
    if card is None:
        raise CardNotFound
    token = _token(card)
    _revoke(card, now=now)
    db.flush()
    if not token:
        return
    try:
        cards().revoke_card(token=token)
    except (PaymentError, DomainError) as exc:
        # Our copy is gone either way; nothing here can charge the card again.
        logger.warning("card %s could not be voided at Multicard: %s", card.id, exc)


def _revoke(card: SavedCard, *, now: datetime) -> None:
    card.status = CardStatus.REVOKED
    card.revoked_at = now
    card.token_encrypted = None
    card.autopay = False


def _token(card: SavedCard) -> str:
    if not card.token_encrypted:
        return ""
    try:
        return decrypt(card.token_encrypted)
    except DecryptionFailed:
        return ""


# --- Charging -------------------------------------------------------------


def charge_due(db: Session, *, now: datetime) -> int:
    """Renew every plan that runs out soon from its owner's card. Charges tried."""
    if not autopay_on():
        return 0
    tried = 0
    for card_id in due_card_ids(db, now=now):
        card = db.scalar(
            select(SavedCard)
            .where(SavedCard.id == card_id, SavedCard.status == CardStatus.ACTIVE)
            .with_for_update(skip_locked=True)
        )
        if card is None:
            db.rollback()
            continue
        try:
            tried += int(charge_card(db, card=card, now=now))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("autopay for card %s failed", card_id)
    return tried


def charge_card(db: Session, *, card: SavedCard, now: datetime) -> bool:
    """One attempt for one card, if one is due. Whether Multicard was asked."""
    subscription = renewing_subscription(db, owner_id=card.owner_id, now=now)
    if subscription is None or not card.autopay:
        return False
    if card.charge_term != subscription.expires_at:
        card.charge_term = subscription.expires_at
        card.charge_attempts = 0
        card.last_charge_uuid = ""
        card.last_charge_outcome = ""
        card.last_charge_error = ""
    adapter = cards()
    if card.last_charge_outcome in (PENDING, CHARGED) and card.last_charge_uuid:
        # A debit that may still land, or one that landed and still left the
        # plan due (its callback refused, the money went back): read it again
        # rather than take a second one beside it.
        try:
            _record(card, adapter.charge_status(uuid=card.last_charge_uuid), now=now)
        except PaymentError as exc:
            logger.warning("charge %s unread: %s", card.last_charge_uuid, exc)
        return False
    if card.last_charge_outcome == NEEDS_CODE:
        return False
    if card.charge_attempts >= MAX_ATTEMPTS:
        return False
    if card.last_charge_at is not None and now - card.last_charge_at < RETRY_GAP:
        return False
    token = _token(card)
    if not token:
        return False
    invoice = _renewal_invoice(db, card=card, subscription=subscription, now=now)
    if invoice is None:
        return False
    # Counted before Multicard is asked, and committed: the callback that
    # settles the bill may come before the answer does, and another run that
    # finds this card meanwhile must see an attempt already under way.
    card.charge_attempts += 1
    card.last_charge_at = now
    card.last_charge_outcome = PENDING
    card.last_charge_uuid = ""
    db.commit()
    try:
        charge = adapter.charge_card(
            token=token,
            number=invoice.number,
            amount_minor=invoice.amount_minor,
            decimal_places=decimal_places(invoice.currency),
            currency=invoice.currency,
            description=f"TargetologAI obunasi: {subscription.plan.name}, "
            f"{invoice.period_days} kun",
        )
    except PaymentError as exc:
        logger.warning("autopay charge for %s not sent: %s", invoice.number, exc)
        charge = Charge(outcome=DECLINED, code="unreachable")
    _record(card, charge, now=now)
    logger.info(
        "autopay %s for invoice %s: %s %s",
        card.pan,
        invoice.number,
        charge.outcome,
        charge.code,
        extra={"owner": str(card.owner_id), "invoice": invoice.number},
    )
    return True


def _renewal_invoice(
    db: Session, *, card: SavedCard, subscription: Subscription, now: datetime
) -> Invoice | None:
    try:
        return create_invoice(db, owner=card.owner, plan=subscription.plan, now=now)
    except DomainError as exc:
        card.charge_attempts = MAX_ATTEMPTS
        card.last_charge_at = now
        card.last_charge_outcome = DECLINED
        card.last_charge_error = f"{CHARGE_ERRORS['invoice']} {exc.message}".strip()[
            :CHARGE_ERROR_MAX
        ]
        logger.warning("no renewal bill for owner %s: %s", card.owner_id, exc)
        return None


def _record(card: SavedCard, charge: Charge, *, now: datetime) -> None:
    if charge.uuid:
        card.last_charge_uuid = charge.uuid
    card.last_charge_outcome = charge.outcome
    if charge.outcome in (CHARGED, PENDING):
        card.last_charge_error = ""
        return
    key = NEEDS_CODE if charge.outcome == NEEDS_CODE else charge.code
    card.last_charge_error = (
        CHARGE_ERRORS.get(key) or charge.details or charge.code or "Rad etildi."
    )[:CHARGE_ERROR_MAX]


__all__ = [
    "Binding",
    "autopay_on",
    "binding_reported",
    "cards",
    "charge_card",
    "charge_due",
    "check_binding",
    "finish_binding",
    "phone_of",
    "remove_card",
    "set_autopay",
    "start_binding",
]
