"""Paynet, as one :class:`~paykit.ports.PaymentPort`.

Written ahead of the contract, on purpose and with the seams visible.
:mod:`paykit.paynet.codes` says which parts are provisional; this module
is the parts that are not - the JSON-RPC envelope, the Basic credential
checked in constant time, the reading of a request into a command, and the
writing of a decision back into a result.

**There is no redirect.** Paynet is an agent network: a payer can settle
at a counter with cash, and what they hand over is a number. So
:meth:`checkout` answers with a reference rather than a URL, and the
screen renders instructions instead of a button. Everything after that -
the callback, the invoice, the subscription - is identical to the two card
providers, which is the whole reason this fits behind the same port.

**A counter payment has no hold step.** Money changes hands and
``PerformTransaction`` arrives without a create before it. The domain's
perform path is written to open an attempt it has not seen before for
exactly this reason; nothing about that is Paynet-specific in the service
layer.
"""

import base64
import hmac
import json
from collections.abc import Mapping
from typing import Any, Final, TypeGuard

from paykit.convert import from_epoch_ms, to_epoch_ms
from paykit.dto import (
    Allowed,
    CallbackRequest,
    Checkout,
    CheckoutRequest,
    Outcome,
    ProviderResponse,
    RawRequest,
    Refused,
    Settled,
    Statement,
    TransactionRecord,
)
from paykit.errors import MalformedCallback, PaymentError, ProviderMisconfigured
from paykit.paynet.codes import (
    ERROR_CODES,
    ERROR_NOTES,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    METHODS,
    PARSE_ERROR,
)
from paykit.refs import (
    CANCELED,
    CREATED,
    INTERNAL,
    MALFORMED,
    PERFORMED,
    REFERENCE,
    REFUNDED,
    UNAUTHORIZED,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    ProviderName,
    TransactionState,
)

PROVIDER: Final = ProviderName("paynet")

# Domain state as a word rather than as a number. Paynet's own state
# encoding is one of the things the contract fixes, and a word survives
# being wrong in a way an integer does not: an operator reading a log sees
# what happened instead of having to look up which sign meant refunded.
STATES: Final[dict[TransactionState, str]] = {
    CREATED: "created",
    PERFORMED: "performed",
    CANCELED: "canceled",
    REFUNDED: "refunded",
}


class PaynetAdapter:
    """Stateless translator between Paynet's JSON-RPC and the domain."""

    def __init__(self, *, username: str, password: str, service_id: str) -> None:
        """Hold the merchant credentials, and nothing else.

        ``service_id`` is not used in a checkout link - there is none - but
        it is what a statement is reconciled against and what a support
        conversation starts from, so it is required rather than optional:
        a deployment that cannot name its own service has not finished
        being configured.
        """
        if not username or not password or not service_id:
            raise ProviderMisconfigured(
                "paynet needs a username, a password and a service id"
            )
        self._username = username
        self._password = password
        self._service_id = service_id

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    # --- Going out -------------------------------------------------------

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """The number the payer gives a cashier or types into the app.

        The invoice number itself, unmodified. It is already short enough
        to read out and unique enough to find, and inventing a second
        identifier here would mean two numbers for one invoice - one on
        the screen and one in support's search box.
        """
        return Checkout(provider=PROVIDER, kind=REFERENCE, reference=request.number)

    # --- Coming in -------------------------------------------------------

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether the Basic credential is this merchant's.

        Constant time, like the other two adapters: the comparison is
        against a secret, and how long a mismatch takes is information.
        """
        header = _header(request.headers, "Authorization")
        expected = base64.b64encode(
            f"{self._username}:{self._password}".encode()
        ).decode()
        return hmac.compare_digest(header.strip(), f"Basic {expected}")

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read one JSON-RPC call as a command about one invoice."""
        payload = _json_object(request.body)
        method = payload.get("method")
        command = METHODS.get(str(method))
        if command is None:
            raise MalformedCallback(f"unknown paynet method: {method!r}")

        params = payload.get("params")
        params = params if isinstance(params, dict) else {}
        account = params.get("account")
        account = account if isinstance(account, dict) else {}

        number = account.get("number") or params.get("number")
        amount = params.get("amount")
        started = params.get("time")
        window_from = params.get("from")
        window_to = params.get("to")
        reason = params.get("reason")
        external = params.get("transactionId") or params.get("id")

        return CallbackRequest(
            provider=PROVIDER,
            command=command,
            correlation=json.dumps(payload.get("id")),
            number=InvoiceNumber(str(number)) if number is not None else None,
            external_id=ExternalId(str(external)) if external else None,
            amount_minor=MinorUnits(int(amount)) if _is_int(amount) else None,
            requested_at=from_epoch_ms(int(started)) if _is_int(started) else None,
            cancel_reason=int(reason) if _is_int(reason) else None,
            window_start=(
                from_epoch_ms(int(window_from)) if _is_int(window_from) else None
            ),
            window_end=from_epoch_ms(int(window_to)) if _is_int(window_to) else None,
            raw=payload,
        )

    # --- Going back ------------------------------------------------------

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The JSON-RPC reply for one decision."""
        if isinstance(outcome, Refused):
            return _error(
                correlation=request.correlation,
                code=ERROR_CODES.get(outcome.reason, ERROR_CODES[INTERNAL]),
                note=ERROR_NOTES.get(outcome.reason, ERROR_NOTES[INTERNAL]),
            )
        return _ok(correlation=request.correlation, result=self._result(outcome))

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        """Answered in the envelope, without the body ever being read."""
        return _error(
            correlation=_correlation(request),
            code=ERROR_CODES[UNAUTHORIZED],
            note=ERROR_NOTES[UNAUTHORIZED],
        )

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        """A parse failure and an unknown method, told apart."""
        correlation = _correlation(request)
        try:
            payload = _json_object(request.body)
        except MalformedCallback:
            return _error(
                correlation=correlation,
                code=PARSE_ERROR,
                note=ERROR_NOTES[MALFORMED],
            )
        code = (
            METHOD_NOT_FOUND
            if str(payload.get("method")) not in METHODS
            else INVALID_REQUEST
        )
        return _error(correlation=correlation, code=code, note=ERROR_NOTES[MALFORMED])

    # --- Internals -------------------------------------------------------

    def _result(self, outcome: Outcome) -> dict[str, Any]:
        if isinstance(outcome, Allowed):
            return {"allow": True, "serviceId": self._service_id}
        if isinstance(outcome, Statement):
            return {"transactions": [_entry(record) for record in outcome.transactions]}
        if isinstance(outcome, Settled):
            return _entry(outcome.transaction)
        raise PaymentError(f"paynet cannot render {type(outcome).__name__}")


def _entry(record: TransactionRecord) -> dict[str, Any]:
    """One attempt, in the field names the envelope carries."""
    return {
        "number": record.number,
        "transaction": record.reference,
        "transactionId": record.external_id,
        "amount": int(record.amount_minor),
        "state": STATES[record.state],
        "createTime": to_epoch_ms(record.created_at),
        "performTime": (
            to_epoch_ms(record.performed_at) if record.performed_at else None
        ),
        "cancelTime": to_epoch_ms(record.canceled_at) if record.canceled_at else None,
        "reason": record.cancel_reason,
    }


def _ok(*, correlation: str, result: Mapping[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        status_code=200,
        body={"jsonrpc": "2.0", "id": _decoded(correlation), "result": dict(result)},
    )


def _error(*, correlation: str, code: int, note: str) -> ProviderResponse:
    return ProviderResponse(
        status_code=200,
        body={
            "jsonrpc": "2.0",
            "id": _decoded(correlation),
            "error": {"code": code, "message": note},
        },
    )


def _correlation(request: RawRequest) -> str:
    try:
        return json.dumps(_json_object(request.body).get("id"))
    except MalformedCallback:
        return ""


def _decoded(correlation: str) -> Any:
    if not correlation:
        return None
    try:
        return json.loads(correlation)
    except ValueError:
        return None


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise MalformedCallback("paynet body was not JSON") from exc
    if not isinstance(payload, dict):
        raise MalformedCallback("paynet body was not a JSON object")
    return payload


def _header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _is_int(value: Any) -> TypeGuard[int]:
    """Whether this is a number the provider meant as one. ``bool`` is not.

    A ``TypeGuard`` so the narrowing survives into the conditional
    expression that follows it - see the note on the Payme side.
    """
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = ["PROVIDER", "PaynetAdapter"]
