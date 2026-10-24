"""Payme, as one :class:`~paykit.ports.PaymentPort`.

Payme's Merchant API is JSON-RPC 2.0 posted to an endpoint we publish.
Three properties of it shape everything below.

**It is a state machine, and Payme is the one driving.** We never call
them. A payer opens the checkout page, and Payme walks our endpoint
through check, create and perform - or create and cancel - asking each
time whether the previous answer still holds. So the adapter's whole job
is reading a method name and writing a result body; the decisions are the
domain's.

**Failures live inside a 200.** A non-2xx tells Payme the endpoint is
broken rather than the request was refused, and enough of those and the
cashbox is suspended. The single exception is a credential that did not
authenticate, and even that is answered in the protocol's own envelope.

**Money is counted in the currency's smallest unit** - tiyin - which is
the same integer this system stores. So there is no amount conversion
here at all, and ``decimal_places`` goes unused: the one thing that could
be off by a hundredfold is the one thing that is a pass-through.
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
from paykit.payme.codes import (
    BASIC_USER,
    ERROR_CODES,
    FIELD_ERRORS,
    INSUFFICIENT_PRIVILEGE,
    INVALID_REQUEST,
    MESSAGES,
    METHOD_NOT_FOUND,
    METHODS,
    PARSE_ERROR,
    STATE_CANCELED,
    STATE_CREATED,
    STATE_PERFORMED,
    STATE_REFUNDED,
)
from paykit.refs import (
    CANCELED,
    CREATED,
    INTERNAL,
    MALFORMED,
    PERFORMED,
    REDIRECT,
    REFUNDED,
    UNAUTHORIZED,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    ProviderName,
    TransactionState,
)

PROVIDER: Final = ProviderName("payme")

# Where a payer is sent. Configuration rather than a constant because the
# sandbox lives at a different host, and a deployment testing against it
# must not need a code change to do so.
CHECKOUT_URL: Final = "https://checkout.paycom.uz"

# Domain state to Payme's number. The reverse map is deliberately absent:
# Payme never tells us a state, it asks us for one.
STATES: Final[dict[TransactionState, int]] = {
    CREATED: STATE_CREATED,
    PERFORMED: STATE_PERFORMED,
    CANCELED: STATE_CANCELED,
    REFUNDED: STATE_REFUNDED,
}

# What a result body carries for a time that has not happened yet. Zero
# and not null: Payme's own validator reads null as a missing field.
NO_TIME: Final = 0


class PaymeAdapter:
    """Stateless translator between Payme's JSON-RPC and the domain."""

    def __init__(
        self,
        *,
        merchant_id: str,
        key: str,
        account_field: str,
        checkout_url: str = CHECKOUT_URL,
    ) -> None:
        """Hold the merchant credentials. Nothing else, and no connection.

        ``account_field`` is the name Payme was told our order key is
        called when the cashbox was set up - it appears in the checkout
        link as ``ac.<field>`` and in every callback's ``account`` object.
        It is configuration because it is chosen in Payme's cabinet by a
        person, and a value compiled in here would be wrong for the second
        cashbox somebody opens.

        Refuses to exist without all three. A blank merchant id builds a
        link that looks correct, sends the payer to a page that turns them
        away, and reports nothing.
        """
        if not merchant_id or not key or not account_field:
            raise ProviderMisconfigured(
                "payme needs a merchant id, a key and an account field name"
            )
        self._merchant_id = merchant_id
        self._key = key
        self._account_field = account_field
        self._checkout_url = checkout_url.rstrip("/")

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    # --- Going out -------------------------------------------------------

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """The checkout link, built offline.

        Payme encodes the whole request into one base64 segment of the
        path: merchant, account, amount, return address and language. The
        separator is a semicolon and the encoding is standard base64 with
        padding - both are Payme's, and both are what their page decodes.
        """
        parts = [
            f"m={self._merchant_id}",
            f"ac.{self._account_field}={request.number}",
            f"a={int(request.amount_minor)}",
        ]
        if request.return_url:
            parts.append(f"c={request.return_url}")
        if request.language:
            parts.append(f"l={request.language}")

        encoded = base64.b64encode(";".join(parts).encode()).decode()
        return Checkout(
            provider=PROVIDER, kind=REDIRECT, url=f"{self._checkout_url}/{encoded}"
        )

    # --- Coming in -------------------------------------------------------

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether the Basic credential is this cashbox's key.

        Compared with :func:`hmac.compare_digest` rather than ``==``. The
        difference is timing: a plain comparison returns sooner on a
        credential that is wrong in the first byte than on one wrong in the
        last, and that is enough to recover a key one byte at a time.

        The username half is fixed by Payme and carries no secret, so it is
        checked as part of the same digest rather than separately.
        """
        header = _header(request.headers, "Authorization")
        expected = base64.b64encode(f"{BASIC_USER}:{self._key}".encode()).decode()
        return hmac.compare_digest(header.strip(), f"Basic {expected}")

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read one JSON-RPC call as a command about one invoice.

        Raises :class:`~paykit.errors.MalformedCallback` for a body that is
        not JSON, not an object, or names a method Payme does not publish.
        Everything else - an unknown invoice, a wrong amount, a
        transaction we never created - parses fine and is the domain's
        answer to give.
        """
        payload = _json_object(request.body)
        method = payload.get("method")
        command = METHODS.get(str(method))
        if command is None:
            raise MalformedCallback(f"unknown payme method: {method!r}")

        params = payload.get("params")
        params = params if isinstance(params, dict) else {}
        account = params.get("account")
        account = account if isinstance(account, dict) else {}

        number = account.get(self._account_field)
        amount = params.get("amount")
        started = params.get("time")
        window_from = params.get("from")
        window_to = params.get("to")
        reason = params.get("reason")

        return CallbackRequest(
            provider=PROVIDER,
            command=command,
            correlation=json.dumps(payload.get("id")),
            number=InvoiceNumber(str(number)) if number is not None else None,
            external_id=_external_id(params.get("id")),
            amount_minor=MinorUnits(int(amount)) if _is_int(amount) else None,
            requested_at=from_epoch_ms(int(started)) if _is_int(started) else None,
            cancel_reason=int(reason) if _is_int(reason) else None,
            window_start=from_epoch_ms(int(window_from))
            if _is_int(window_from)
            else None,
            window_end=from_epoch_ms(int(window_to)) if _is_int(window_to) else None,
            raw=payload,
        )

    # --- Going back ------------------------------------------------------

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The JSON-RPC reply for one decision."""
        if isinstance(outcome, Refused):
            return self._error(request=request, outcome=outcome)
        return _result(request=request, result=self._result_body(outcome))

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        """Payme's own code for a credential it does not recognise.

        Still a 200 with an error object, and still without reading the
        body: an endpoint that answers 401 is one Payme reports as down.
        """
        return _error_body(
            correlation=_correlation(request),
            code=INSUFFICIENT_PRIVILEGE,
            message=MESSAGES[UNAUTHORIZED],
            field="",
        )

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        """Three protocol failures, told apart so the cause is readable.

        A body that is not JSON is a parse error; a body that is JSON but
        names a method Payme does not publish is a method error; anything
        else is an invalid request. One code for all three would leave an
        operator unable to tell a proxy mangling bodies from a protocol
        version moving under us.
        """
        correlation = _correlation(request)
        try:
            payload = _json_object(request.body)
        except MalformedCallback:
            return _error_body(
                correlation=correlation,
                code=PARSE_ERROR,
                message=MESSAGES[MALFORMED],
                field="",
            )

        code = (
            METHOD_NOT_FOUND
            if str(payload.get("method")) not in METHODS
            else INVALID_REQUEST
        )
        return _error_body(
            correlation=correlation,
            code=code,
            message=MESSAGES[MALFORMED],
            field="",
        )

    # --- Internals -------------------------------------------------------

    def _result_body(self, outcome: Outcome) -> dict[str, Any]:
        """The ``result`` object for a decision that was not a refusal."""
        if isinstance(outcome, Allowed):
            return {"allow": True}
        if isinstance(outcome, Statement):
            return {
                "transactions": [
                    self._statement_entry(record) for record in outcome.transactions
                ]
            }
        if isinstance(outcome, Settled):
            # ``reason`` on every reply, for the same reason as the times:
            # ``CheckTransaction`` requires it, null while nothing was
            # cancelled, and the others ignore it.
            return _times(outcome.transaction) | {
                "transaction": outcome.transaction.reference,
                "state": STATES[outcome.transaction.state],
                "reason": outcome.transaction.cancel_reason,
            }
        # Every member of the union is handled above. Reached only if a new
        # outcome type is added without a branch here, which is a bug in
        # this file rather than anything a provider did.
        raise PaymentError(f"payme cannot render {type(outcome).__name__}")

    def _statement_entry(self, record: TransactionRecord) -> dict[str, Any]:
        """One row of ``GetStatement``, in Payme's own field names.

        Carries the account object as well as the times, because a
        statement is what Payme reconciles against and it has to be able
        to tell which order each row belongs to without asking again.
        """
        return _times(record) | {
            "id": record.external_id,
            "time": to_epoch_ms(record.requested_at or record.created_at),
            "amount": int(record.amount_minor),
            "account": {self._account_field: record.number},
            "transaction": record.reference,
            "state": STATES[record.state],
            "reason": record.cancel_reason,
        }

    def _error(self, *, request: CallbackRequest, outcome: Refused) -> ProviderResponse:
        """A refusal, in the code and the three languages Payme asks for."""
        reason = outcome.reason
        return _error_body(
            correlation=request.correlation,
            code=ERROR_CODES.get(reason, ERROR_CODES[INTERNAL]),
            message=MESSAGES.get(reason, MESSAGES[INTERNAL]),
            field=self._account_field if reason in FIELD_ERRORS else "",
        )


def _times(record: TransactionRecord) -> dict[str, Any]:
    """The three timestamps every Payme result carries.

    Zero for the ones that have not happened, which is Payme's own way of
    saying "not yet" - and the reason this is one helper rather than
    repeated: a result that omits a field is rejected by their validator,
    and the omission is easy to make three times and notice once.
    """
    return {
        "create_time": to_epoch_ms(record.created_at),
        "perform_time": to_epoch_ms(record.performed_at)
        if record.performed_at
        else NO_TIME,
        "cancel_time": to_epoch_ms(record.canceled_at)
        if record.canceled_at
        else NO_TIME,
    }


def _result(*, request: CallbackRequest, result: Mapping[str, Any]) -> ProviderResponse:
    """A successful JSON-RPC envelope with the request's id echoed."""
    return ProviderResponse(
        status_code=200,
        body={
            "jsonrpc": "2.0",
            "id": _decoded(request.correlation),
            "result": dict(result),
        },
    )


def _error_body(
    *, correlation: str, code: int, message: Mapping[str, str], field: str
) -> ProviderResponse:
    """A JSON-RPC error envelope.

    ``data`` is present only for the merchant-defined band, where Payme
    uses it to highlight the field the payer typed wrong. Sending it on a
    protocol-level error makes their validator complain.
    """
    error: dict[str, Any] = {"code": code, "message": dict(message)}
    if field:
        error["data"] = field
    return ProviderResponse(
        status_code=200,
        body={"jsonrpc": "2.0", "id": _decoded(correlation), "error": error},
    )


def _correlation(request: RawRequest) -> str:
    """The request id, recovered from a body that may not parse.

    Empty when the body is unreadable, which renders as a null id - the
    honest answer, and one Payme accepts on an error reply.
    """
    try:
        return json.dumps(_json_object(request.body).get("id"))
    except MalformedCallback:
        return ""


def _decoded(correlation: str) -> Any:
    """The request id as JSON saw it: a number, a string, or null."""
    if not correlation:
        return None
    try:
        return json.loads(correlation)
    except ValueError:
        return None


def _json_object(body: bytes) -> dict[str, Any]:
    """The body as a JSON object, or a malformed callback."""
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise MalformedCallback("payme body was not JSON") from exc
    if not isinstance(payload, dict):
        raise MalformedCallback("payme body was not a JSON object")
    return payload


def _header(headers: Mapping[str, str], name: str) -> str:
    """One header, case-insensitively. WSGI and ASGI disagree on casing."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _external_id(value: Any) -> ExternalId | None:
    """Payme's transaction id, as a string or not at all."""
    return ExternalId(str(value)) if isinstance(value, str) and value else None


def _is_int(value: Any) -> TypeGuard[int]:
    """Whether this is a number the provider meant as one. ``bool`` is not.

    A ``TypeGuard`` rather than a plain ``bool`` so the narrowing survives
    into the conditional expression that follows it. Without it every
    ``int(value)`` beside a check like this is an unchecked call on
    ``Any | None`` - which is exactly the shape that turns a missing field
    into a ``TypeError`` on the payment path.
    """
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = ["CHECKOUT_URL", "PROVIDER", "PaymeAdapter"]
