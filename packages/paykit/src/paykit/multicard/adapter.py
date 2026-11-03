"""Multicard (Rahmat), as one :class:`~paykit.ports.PaymentPort`.

The payer is sent to Multicard's own checkout page, so no card number ever
reaches this product. The page exists once an invoice has been created
through Multicard's API (:mod:`paykit.multicard.client`).

Two requests may come back, and both are signed with the shop's secret:

- the **payment callback**, sent to the invoice's ``callback_url`` after the
  card is debited and *before* the payment is final. Answering anything but
  ``200`` with ``success: true`` cancels it and returns the money, which is
  why a refusal here is safe. The signature is
  ``md5(store_id + invoice_id + amount + secret)``.
- the optional **status webhook**, sent on every status change if it is
  switched on in Multicard's cabinet. It carries ``status`` and is signed
  ``sha1(uuid + invoice_id + amount + secret)`` - a signature that leaves
  ``status`` out, so it is acknowledged and never acted on.
"""

import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from paykit.dto import (
    CallbackRequest,
    Checkout,
    CheckoutRequest,
    Outcome,
    ProviderResponse,
    RawRequest,
    Refused,
    Settled,
)
from paykit.errors import MalformedCallback, ProviderMisconfigured, ProviderUnavailable
from paykit.multicard.cards import (
    DECLINED,
    NEEDS_CODE,
    PENDING,
    UNSETTLED_CODES,
    BindSession,
    BoundCard,
    Charge,
    bound_card_of,
    charge_of,
)
from paykit.multicard.cards import DRAFT as DRAFT_STATUS
from paykit.multicard.client import (
    MulticardClient,
    MulticardOutcomeUnknown,
    MulticardRefused,
)
from paykit.multicard.codes import (
    CURRENCY,
    LANGUAGES,
    MESSAGES,
    OK_MESSAGE,
    TIYIN_PLACES,
    TOKEN_ZONE,
)
from paykit.refs import (
    INTERNAL,
    MALFORMED,
    PERFORM,
    REDIRECT,
    STATUS,
    UNAUTHORIZED,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    ProviderName,
)

PROVIDER: Final = ProviderName("multicard")

# Kept out of the stored copy of a callback: a card token lets a holder of
# our credentials charge the card again, and nothing here ever needs it.
NEVER_STORED: Final = frozenset({"card_token", "sign"})


class MulticardAdapter:
    """Creates Multicard invoices and answers Multicard's signed callbacks."""

    def __init__(
        self,
        *,
        client: MulticardClient,
        store_id: str,
        secret: str,
        callback_url: str,
        decimal_places: int,
        ofd_mxik: str,
        ofd_package_code: str,
        ofd_name: str,
        ofd_vat: int | None = None,
        ofd_tin: str = "",
        allowed_ips: Iterable[str] = (),
    ) -> None:
        if not store_id or not secret or not callback_url:
            raise ProviderMisconfigured(
                "multicard needs a store id, a secret and a callback url"
            )
        if not ofd_mxik or not ofd_package_code:
            raise ProviderMisconfigured(
                "multicard needs an IKPU (mxik) and a package code for the receipt"
            )
        self._client = client
        self._store_id = str(store_id)
        self._secret = secret
        self._callback_url = callback_url
        self._decimal_places = decimal_places
        self._ofd = {
            "mxik": ofd_mxik,
            "package_code": ofd_package_code,
            "name": ofd_name,
        }
        self._vat = ofd_vat
        self._tin = ofd_tin
        self._allowed_ips = frozenset(ip.strip() for ip in allowed_ips if ip.strip())

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """An invoice at Multicard, and the page its payer is sent to."""
        if request.currency and request.currency.upper() != CURRENCY:
            raise ProviderMisconfigured(
                f"multicard takes only {CURRENCY}, not {request.currency}"
            )
        tiyin = _tiyin(request.amount_minor, request.decimal_places)
        if tiyin <= 0:
            raise ProviderMisconfigured("multicard cannot take an empty amount")
        payload: dict[str, Any] = {
            "store_id": _store(self._store_id),
            "amount": tiyin,
            "invoice_id": request.number,
            "callback_url": self._callback_url,
            "ofd": [self._receipt_item(tiyin, request.description)],
        }
        if request.return_url:
            payload["return_url"] = request.return_url
            payload["return_error_url"] = request.return_url
        if request.language in LANGUAGES:
            payload["lang"] = request.language
        if request.ttl_seconds:
            payload["ttl"] = int(request.ttl_seconds)
        data = self._client.create_invoice(payload)
        url = str(data.get("checkout_url") or data.get("short_link") or "")
        if not url:
            raise ProviderUnavailable("multicard created an invoice without a page")
        return Checkout(
            provider=PROVIDER,
            kind=REDIRECT,
            url=url,
            reference=str(data.get("uuid", "")),
        )

    # --- Saved cards (paykit.multicard.cards) ---------------------------

    def start_card_binding(
        self, *, phone: str, redirect_url: str, decline_url: str, callback_url: str
    ) -> BindSession:
        """A Multicard page, good for 15 minutes, where the payer adds a card."""
        data = self._client.bind_card(
            {
                "store_id": _store(self._store_id),
                "phone": phone,
                "redirect_url": redirect_url,
                "redirect_decline_url": decline_url,
                "callback_url": callback_url,
            }
        )
        session_id = str(data.get("session_id") or "")
        form_url = str(data.get("form_url") or "")
        if not session_id or not form_url:
            raise ProviderUnavailable("multicard opened a card page without a link")
        return BindSession(session_id=session_id, form_url=form_url)

    def bound_card(self, *, session_id: str) -> BoundCard | None:
        """The card a binding page added, or ``None`` while there is none yet."""
        try:
            data = self._client.bound_card(session_id)
        except MulticardRefused:
            return None
        return bound_card_of(data) if data else None

    def revoke_card(self, *, token: str) -> None:
        """The token stops working at Multicard."""
        self._client.revoke_card(token)

    def charge_card(
        self,
        *,
        token: str,
        number: str,
        amount_minor: int,
        decimal_places: int,
        currency: str,
        description: str = "",
    ) -> Charge:
        """Take an invoice's amount from a saved card, with nobody at the screen.

        The debit settles the invoice through the ordinary signed payment
        callback; what comes back here only says how far the attempt got.
        """
        if currency and currency.upper() != CURRENCY:
            raise ProviderMisconfigured(
                f"multicard takes only {CURRENCY}, not {currency}"
            )
        tiyin = _tiyin(amount_minor, decimal_places)
        if tiyin <= 0:
            raise ProviderMisconfigured("multicard cannot take an empty amount")
        try:
            created = self._client.create_payment(
                {
                    "card": {"token": token},
                    "amount": tiyin,
                    "store_id": _store(self._store_id),
                    "invoice_id": number,
                    "callback_url": self._callback_url,
                    "ofd": [self._receipt_item(tiyin, description)],
                }
            )
        except MulticardRefused as exc:
            # Nothing was debited: a payment that was never created moves no money.
            return Charge(outcome=DECLINED, code=exc.code, details=exc.details)
        uuid = str(created.get("uuid") or "")
        if not uuid:
            raise ProviderUnavailable("multicard created a payment without a uuid")
        if created.get("otp_hash"):
            return Charge(outcome=NEEDS_CODE, uuid=uuid, status=DRAFT_STATUS)
        try:
            return charge_of(self._client.confirm_payment(uuid))
        except MulticardRefused as exc:
            outcome = PENDING if exc.code in UNSETTLED_CODES else DECLINED
            return Charge(
                outcome=outcome, uuid=uuid, code=exc.code, details=exc.details
            )
        except MulticardOutcomeUnknown:
            return Charge(outcome=PENDING, uuid=uuid)

    def charge_status(self, *, uuid: str) -> Charge:
        """A charge read again, for one that was left :data:`PENDING`."""
        return charge_of(self._client.payment(uuid))

    def _receipt_item(self, tiyin: int, description: str) -> dict[str, Any]:
        item: dict[str, Any] = {
            **self._ofd,
            "name": description or self._ofd["name"],
            "qty": 1,
            "price": tiyin,
            "total": tiyin,
        }
        if self._vat is not None:
            item["vat"] = self._vat
        if self._tin:
            item["tin"] = self._tin
        return item

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether this request came from Multicard, for our shop."""
        if self._allowed_ips and _client_ip(request.headers) not in self._allowed_ips:
            return False
        body = _json(request.body)
        if body is None:
            return False
        given = str(body.get("sign", "")).strip().lower()
        if not given:
            return False
        if "status" in body:
            expected = _sha1(
                f"{body.get('uuid', '')}{body.get('invoice_id', '')}"
                f"{body.get('amount', '')}{self._secret}"
            )
        else:
            if str(body.get("store_id", "")) != self._store_id:
                return False
            expected = _md5(
                f"{body.get('store_id', '')}{body.get('invoice_id', '')}"
                f"{body.get('amount', '')}{self._secret}"
            )
        return hmac.compare_digest(expected, given)

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read one callback as a command about one invoice."""
        body = _json(request.body)
        if body is None:
            raise MalformedCallback("multicard sent a body that is not a JSON object")
        number = str(body.get("invoice_id", "")).strip()
        uuid = str(body.get("uuid", "")).strip()
        if not number or not uuid:
            raise MalformedCallback("multicard callback without invoice_id or uuid")
        try:
            tiyin = int(body.get("amount"))
        except (TypeError, ValueError) as exc:
            raise MalformedCallback("multicard amount was not a whole number") from exc
        # The status webhook's signature does not cover ``status``, so one
        # captured webhook could be replayed as "success" or "revert". It is
        # acknowledged and never acted on; the signed payment callback is the
        # only thing that settles an invoice.
        command = STATUS if "status" in body else PERFORM
        return CallbackRequest(
            provider=PROVIDER,
            command=command,
            correlation="webhook" if "status" in body else "callback",
            number=InvoiceNumber(number),
            external_id=ExternalId(uuid),
            amount_minor=MinorUnits(_minor(tiyin, self._decimal_places)),
            requested_at=_moment(body.get("payment_time")),
            raw={key: value for key, value in body.items() if key not in NEVER_STORED},
        )

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """``success: true`` lets the payment through; anything else returns the money."""
        if request.correlation == "webhook":
            return ProviderResponse(status_code=200, body={"success": True})
        if isinstance(outcome, Settled):
            return ProviderResponse(
                status_code=200, body={"success": True, "message": OK_MESSAGE}
            )
        reason = outcome.reason if isinstance(outcome, Refused) else MALFORMED
        return ProviderResponse(
            status_code=200,
            body={
                "success": False,
                "message": MESSAGES.get(reason, MESSAGES[INTERNAL]),
            },
        )

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        return ProviderResponse(
            status_code=403, body={"success": False, "message": MESSAGES[UNAUTHORIZED]}
        )

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        return ProviderResponse(
            status_code=400, body={"success": False, "message": MESSAGES[MALFORMED]}
        )


def _tiyin(amount_minor: int, decimal_places: int) -> int:
    """The invoice's minor units as tiyin."""
    return int(amount_minor) * 10 ** (TIYIN_PLACES - decimal_places)


def _minor(tiyin: int, decimal_places: int) -> int:
    """Tiyin back in the invoice's minor units. Never rounded: a fraction mismatches."""
    shift = TIYIN_PLACES - decimal_places
    if shift <= 0:
        return tiyin * 10 ** (-shift)
    whole, rest = divmod(tiyin, 10**shift)
    return whole if rest == 0 else -1


def _store(value: str) -> int | str:
    return int(value) if value.isdigit() else value


def _json(body: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(body or b"{}")
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def _client_ip(headers: Mapping[str, str]) -> str:
    lowered = {key.lower(): value for key, value in headers.items()}
    real = lowered.get("x-real-ip", "").strip()
    if real:
        return real
    return lowered.get("x-forwarded-for", "").split(",")[0].strip()


def _moment(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo(TOKEN_ZONE)
        )
    except ValueError:
        return None


__all__ = ["NEVER_STORED", "PROVIDER", "MulticardAdapter"]
