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
    WRONG_CODE,
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
    CODE_RESEND_SECONDS,
    CODE_SENDS,
    MAX_ATTEMPTS,
    PHONE_DIGITS,
    PHONE_PREFIX,
    PROVIDER,
    RETRY_GAP,
    CardStatus,
)
from app.modules.autopay.exceptions import (
    AutopayUnavailable,
    CardCodeLimit,
    CardCodeStale,
    CardCodeTooSoon,
    CardCodeWrong,
    CardDeclined,
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
from app.modules.billing.constants import PAYABLE_INVOICE_STATUSES, WalletChoice
from app.modules.billing.exceptions import InvoiceNotPayable
from app.modules.billing.models import Invoice, Plan
from app.modules.billing.selectors import next_term_plan
from app.modules.billing.services import create_invoice, price_invoice
from app.modules.billing.services.invoices import receipt_line

logger = logging.getLogger(__name__)

# The one card type Multicard asks the owner's phone for.
HUMO = "humo"


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


def return_paths(back: str) -> tuple[str, str]:
    """Where Multicard sends the owner after its card page: bound, declined.

    ``back`` is a cabinet path the owner was on (a checkout); anything that
    is not plainly one falls back to the billing screen.
    """
    plain = (
        back.startswith("/app/")
        and "//" not in back
        and "\\" not in back
        and "#" not in back
        and all(ch.isprintable() and not ch.isspace() for ch in back)
    )
    if not plain:
        return CARD_DONE_PATH, CARD_DECLINED_PATH
    joint = "&" if "?" in back else "?"
    return f"{back}{joint}card=bound", f"{back}{joint}card=declined"


def start_binding(
    db: Session,
    *,
    user: User,
    phone: str,
    consent: bool,
    now: datetime,
    autopay: bool = True,
    back: str = "",
    card_type: str = "",
) -> Binding:
    """A Multicard page where the owner adds the card bills are paid from.

    Multicard needs the owner's phone for a Humo card only, and checks a
    phone it is given against the card's SMS number (Uzcard, Humo); the code
    goes to the card's own number. So a card the owner says is not Humo is
    bound with no phone - a card from abroad has no 998 number to give.
    """
    if not consent:
        raise ConsentRequired
    adapter = cards()
    kind = card_type.strip().lower()
    number = "" if kind and kind != HUMO else phone_of(phone, user=user)
    done, declined = return_paths(back)
    try:
        session = adapter.start_card_binding(
            phone=number,
            redirect_url=settings.site_url + done,
            decline_url=settings.site_url + declined,
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
            # What the owner chose before the page; kept once the card is bound.
            autopay=autopay,
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
    # Start is never sold twice: its card pays for Standart instead.
    plan = next_term_plan(db, plan=subscription.plan)
    if plan is None:
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
    invoice = _renewal_invoice(db, card=card, plan=plan, now=now)
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
            description=f"TargetologAI obunasi: {plan.name}, {invoice.period_days} kun",
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
    db: Session, *, card: SavedCard, plan: Plan, now: datetime
) -> Invoice | None:
    try:
        invoice = create_invoice(db, owner=card.owner, plan=plan, now=now)
        # Everything the term held goes on with it: the extra pages and the
        # manager seats beside the plan. Nothing is left out and no code or
        # wallet money is spent with nobody at the screen; the owner who wants
        # less renews by hand and unticks it.
        return price_invoice(
            db, invoice=invoice, promo_code="", wallet=WalletChoice.KEEP, now=now
        )
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


# --- Paying a bill from the card, its owner at the screen -------------------


@dataclass(frozen=True, slots=True)
class CardPayment:
    """How far a bill paid from the saved card got.

    ``page_url`` is set when the payment must be confirmed on Multicard's
    page (an SMS code or 3-D Secure, as the card needs). Otherwise
    ``charge`` is set when Multicard texted the card's owner a code: it is
    handed back with that code to :func:`confirm_card_payment`, or to
    :func:`resend_card_code` for a new code after ``resend_in`` seconds.
    """

    charge: str = ""
    resend_in: int = 0
    # Multicard's page for a payment that must be confirmed: the payer goes
    # there instead of typing a code here, for any card.
    page_url: str = ""

    @property
    def needs_code(self) -> bool:
        return bool(self.charge)


def pay_from_card(
    db: Session, *, user: User, invoice: Invoice, now: datetime, sends: int = 1
) -> CardPayment:
    """Take a bill's amount from its owner's saved card.

    The bill itself is settled by Multicard's signed payment callback, as
    one paid on its page is; a refusal is raised in the owner's words.
    """
    if invoice.status not in PAYABLE_INVOICE_STATUSES or invoice.expires_at <= now:
        raise InvoiceNotPayable
    adapter = cards()
    card = active_card(db, owner=user)
    token = _token(card) if card is not None else ""
    if not token:
        raise CardNotFound
    try:
        charge = adapter.charge_card(
            token=token,
            number=invoice.number,
            amount_minor=invoice.amount_minor,
            decimal_places=decimal_places(invoice.currency),
            currency=invoice.currency,
            description=receipt_line(invoice),
        )
    except PaymentError as exc:
        logger.warning("card payment for %s not sent: %s", invoice.number, exc)
        raise CardServiceDown from exc
    logger.info(
        "card payment for invoice %s: %s %s",
        invoice.number,
        charge.outcome,
        charge.code,
        extra={"owner": str(user.id), "invoice": invoice.number},
    )
    if charge.outcome == NEEDS_CODE and charge.checkout_url:
        return CardPayment(page_url=charge.checkout_url)
    if charge.outcome == NEEDS_CODE:
        return CardPayment(
            charge=_charge_token(invoice.number, charge.uuid, now=now, sends=sends),
            resend_in=CODE_RESEND_SECONDS,
        )
    if charge.outcome == DECLINED:
        raise CardDeclined(_refusal(charge))
    return CardPayment()


def confirm_card_payment(
    db: Session, *, user: User, invoice: Invoice, charge: str, code: str, now: datetime
) -> None:
    """Debit a card payment with the code Multicard texted the card's owner."""
    if invoice.status not in PAYABLE_INVOICE_STATUSES or invoice.expires_at <= now:
        raise InvoiceNotPayable
    uuid, _, _ = _read_charge(charge, invoice)
    digits = "".join(ch for ch in code if ch.isdigit())
    if not digits:
        raise CardCodeWrong
    result = cards().confirm_charge(uuid=uuid, code=digits)
    logger.info(
        "card payment for invoice %s confirmed: %s %s",
        invoice.number,
        result.outcome,
        result.code,
        extra={"owner": str(user.id), "invoice": invoice.number},
    )
    if result.outcome != DECLINED:
        return
    if result.code == WRONG_CODE:
        raise CardCodeWrong
    raise CardDeclined(_refusal(result))


def resend_card_code(
    db: Session, *, user: User, invoice: Invoice, charge: str, now: datetime
) -> CardPayment:
    """A new SMS code for a bill waiting for one.

    Multicard has no way to send a payment's code again, so the waiting
    payment is dropped and a new one is made for the same bill: Multicard
    texts its own code. A card that no longer asks for a code is simply
    charged, and the answer then carries no ``charge``.
    """
    if invoice.status not in PAYABLE_INVOICE_STATUSES or invoice.expires_at <= now:
        raise InvoiceNotPayable
    uuid, issued, sends = _read_charge(charge, invoice)
    left = CODE_RESEND_SECONDS - int(now.timestamp() - issued)
    if left > 0:
        raise CardCodeTooSoon(left)
    if sends >= CODE_SENDS:
        raise CardCodeLimit
    try:
        # A payment waiting for its code has moved no money; dropping it only
        # keeps the old code from being used. Refused or unanswered, it stays
        # a draft Multicard will not debit without that code.
        cards().refund(external_id=uuid)
    except PaymentError as exc:
        logger.info("waiting card payment %s not dropped: %s", uuid, exc)
    return pay_from_card(db, user=user, invoice=invoice, now=now, sends=sends + 1)


def _charge_token(number: str, uuid: str, *, now: datetime, sends: int) -> str:
    return encrypt(f"{number}:{uuid}:{int(now.timestamp())}:{sends}").decode()


def _read_charge(charge: str, invoice: Invoice) -> tuple[str, int, int]:
    """The payment's uuid, when its code was sent and how many were sent."""
    try:
        parts = decrypt(charge.encode()).split(":")
    except DecryptionFailed as exc:
        raise CardCodeStale from exc
    number, uuid = [*parts, "", ""][:2]
    if number != invoice.number or not uuid:
        raise CardCodeStale
    # A token made before resending existed carries neither.
    issued = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    sends = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
    return uuid, issued, sends


def _refusal(charge: Charge) -> str:
    return (CHARGE_ERRORS.get(charge.code) or charge.details or "")[:CHARGE_ERROR_MAX]


__all__ = [
    "Binding",
    "CardPayment",
    "autopay_on",
    "binding_reported",
    "cards",
    "charge_card",
    "charge_due",
    "check_binding",
    "confirm_card_payment",
    "finish_binding",
    "pay_from_card",
    "phone_of",
    "remove_card",
    "resend_card_code",
    "return_paths",
    "set_autopay",
    "start_binding",
]
