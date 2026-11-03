"""A payer's card kept at Multicard, and money taken from it later.

Two halves, both documented by Multicard as «Привязка карт (форма)» and
«Оплата на странице Партнера»:

- **Binding.** ``POST /payment/card/bind`` opens a Multicard page for 15
  minutes where the payer adds a card; Multicard texts the card's owner a
  code. What comes back is a *token*: no card number ever reaches us. The
  callback that announces a bound card is not signed, so a card is only
  ever believed when ``GET /payment/card/bind/{session_id}`` says so.
- **Charging.** ``POST /payment`` with the token creates a payment that has
  moved no money; ``PUT /payment/{uuid}`` with an empty body debits it. An
  empty body is enough only when Multicard has switched on debits without a
  code for the shop - otherwise the answer carries an ``otp_hash`` and a
  charge with nobody at the screen cannot go on.

The debit is then announced by the same signed payment callback an invoice
paid on Multicard's page sends, with our invoice number in ``invoice_id``,
so it is settled where every other payment is.
"""

from dataclasses import dataclass
from typing import Any, Final

# Multicard's payment statuses (PaymentStatusEnum).
DRAFT: Final = "draft"
PROGRESS: Final = "progress"
BILLING: Final = "billing"
SUCCESS: Final = "success"
ERROR: Final = "error"
REVERT: Final = "revert"

# A card the payer finished adding.
ACTIVE_CARD: Final = "active"

# What a charge came to, in this package's words.
CHARGED: Final = "charged"
DECLINED: Final = "declined"
PENDING: Final = "pending"
NEEDS_CODE: Final = "needs_code"

# Refusals after which the debit may still have happened: Multicard asks
# for the payment to be read again until it is final.
UNSETTLED_CODES: Final = frozenset({"ERROR_DEBIT_UNKNOWN", "ERROR_CALLBACK_TIMEOUT"})


@dataclass(frozen=True, slots=True)
class BindSession:
    session_id: str
    form_url: str


@dataclass(frozen=True, slots=True)
class BoundCard:
    token: str
    pan: str
    ps: str
    holder: str
    phone: str
    status: str

    @property
    def usable(self) -> bool:
        return self.status == ACTIVE_CARD and bool(self.token)


@dataclass(frozen=True, slots=True)
class Charge:
    """One attempt to take money from a saved card.

    ``outcome`` is :data:`CHARGED`, :data:`DECLINED`, :data:`PENDING` (the
    debit may still land: read it again by ``uuid``) or :data:`NEEDS_CODE`
    (the shop is not allowed to debit without the payer's SMS code).
    """

    outcome: str
    uuid: str = ""
    status: str = ""
    code: str = ""
    details: str = ""


def bound_card_of(data: dict[str, Any]) -> BoundCard:
    return BoundCard(
        token=str(data.get("card_token") or ""),
        pan=str(data.get("card_pan") or ""),
        ps=str(data.get("ps") or ""),
        holder=str(data.get("holder_name") or ""),
        phone=str(data.get("phone") or ""),
        status=str(data.get("status") or ""),
    )


def charge_of(data: dict[str, Any]) -> Charge:
    """A payment as Multicard holds it, in this package's words."""
    status = str(data.get("status") or "")
    uuid = str(data.get("uuid") or "")
    if status == SUCCESS:
        outcome = CHARGED
    elif status in (ERROR, REVERT):
        outcome = DECLINED
    else:
        outcome = PENDING
    return Charge(
        outcome=outcome,
        uuid=uuid,
        status=status,
        code=str(data.get("ps_response_code") or ""),
    )


__all__ = [
    "ACTIVE_CARD",
    "CHARGED",
    "DECLINED",
    "NEEDS_CODE",
    "PENDING",
    "UNSETTLED_CODES",
    "BindSession",
    "BoundCard",
    "Charge",
    "bound_card_of",
    "charge_of",
]
