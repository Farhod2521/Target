"""Payme, as one :class:`~paykit.ports.PaymentPort`."""

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

CHECKOUT_URL: Final = "https://checkout.paycom.uz"

STATES: Final[dict[TransactionState, int]] = {
    CREATED: STATE_CREATED,
    PERFORMED: STATE_PERFORMED,
    CANCELED: STATE_CANCELED,
    REFUNDED: STATE_REFUNDED,
}

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
        """Hold the merchant credentials. Nothing else, and no connection."""
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

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """The checkout link, built offline."""
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

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether the Basic credential is this cashbox's key."""
        header = _header(request.headers, "Authorization")
        expected = base64.b64encode(f"{BASIC_USER}:{self._key}".encode()).decode()
        return hmac.compare_digest(header.strip(), f"Basic {expected}")

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read one JSON-RPC call as a command about one invoice."""
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

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The JSON-RPC reply for one decision."""
        if isinstance(outcome, Refused):
            return self._error(request=request, outcome=outcome)
        return _result(request=request, result=self._result_body(outcome))

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        """Payme's own code for a credential it does not recognise."""
        return _error_body(
            correlation=_correlation(request),
            code=INSUFFICIENT_PRIVILEGE,
            message=MESSAGES[UNAUTHORIZED],
            field="",
        )

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        """Three protocol failures, told apart so the cause is readable."""
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
            return _times(outcome.transaction) | {
                "transaction": outcome.transaction.reference,
                "state": STATES[outcome.transaction.state],
                "reason": outcome.transaction.cancel_reason,
            }
        raise PaymentError(f"payme cannot render {type(outcome).__name__}")

    def _statement_entry(self, record: TransactionRecord) -> dict[str, Any]:
        """One row of ``GetStatement``, in Payme's own field names."""
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
    """The three timestamps every Payme result carries."""
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
    """A JSON-RPC error envelope."""
    error: dict[str, Any] = {"code": code, "message": dict(message)}
    if field:
        error["data"] = field
    return ProviderResponse(
        status_code=200,
        body={"jsonrpc": "2.0", "id": _decoded(correlation), "error": error},
    )


def _correlation(request: RawRequest) -> str:
    """The request id, recovered from a body that may not parse."""
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
    """Whether this is a number the provider meant as one. ``bool`` is not."""
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = ["CHECKOUT_URL", "PROVIDER", "PaymeAdapter"]
