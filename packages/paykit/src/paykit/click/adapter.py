"""Click, as one :class:`~paykit.ports.PaymentPort`."""

import hashlib
import hmac
from collections.abc import Mapping
from decimal import InvalidOperation
from typing import Any, Final
from urllib.parse import quote, urlencode

from paykit.click.codes import (
    ACTION_COMPLETE,
    ACTION_PREPARE,
    CHECKOUT_URL,
    COMPLETE_SIGNED,
    ERROR_CODES,
    ERROR_NOTES,
    OK,
    PREPARE_SIGNED,
    SECRET_AFTER,
    SUCCESS_NOTE,
)
from paykit.convert import to_minor, to_units
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
from paykit.errors import MalformedCallback, ProviderMisconfigured
from paykit.refs import (
    CANCEL,
    CREATE,
    INTERNAL,
    MALFORMED,
    PERFORM,
    REDIRECT,
    UNAUTHORIZED,
    Command,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    ProviderName,
)

PROVIDER: Final = ProviderName("click")

ORDER_PARAM: Final = "transaction_param"


class ClickAdapter:
    """Stateless translator between Click's form posts and the domain."""

    def __init__(
        self,
        *,
        service_id: str,
        merchant_id: str,
        secret_key: str,
        decimal_places: int,
        checkout_url: str = CHECKOUT_URL,
    ) -> None:
        """Hold the shop's credentials and how its currency subdivides."""
        if not service_id or not merchant_id or not secret_key:
            raise ProviderMisconfigured(
                "click needs a service id, a merchant id and a secret key"
            )
        self._service_id = service_id
        self._merchant_id = merchant_id
        self._secret_key = secret_key
        self._decimal_places = decimal_places
        self._checkout_url = checkout_url

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """The checkout link, built offline."""
        params = {
            "service_id": self._service_id,
            "merchant_id": self._merchant_id,
            "amount": to_units(
                amount_minor=request.amount_minor,
                decimal_places=request.decimal_places,
            ),
            ORDER_PARAM: request.number,
        }
        if request.return_url:
            params["return_url"] = request.return_url

        query = urlencode(params, quote_via=quote, safe=":/")
        return Checkout(
            provider=PROVIDER, kind=REDIRECT, url=f"{self._checkout_url}?{query}"
        )

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether the digest over this post matches our secret key."""
        form = request.form
        action = _int(form.get("action"))
        fields: tuple[str, ...]
        if action == ACTION_PREPARE:
            fields = PREPARE_SIGNED
        elif action == ACTION_COMPLETE:
            fields = COMPLETE_SIGNED
        else:
            return False

        return hmac.compare_digest(
            self._signature(form=form, fields=fields),
            str(form.get("sign_string", "")).strip().lower(),
        )

    def parse(self, *, request: RawRequest) -> CallbackRequest:
        """Read one post as a command about one invoice."""
        form = request.form
        command = self._command(form=form)

        try:
            amount = to_minor(
                units=str(form.get("amount", "")).strip() or "0",
                decimal_places=self._decimal_places,
            )
        except (InvalidOperation, ValueError) as exc:
            raise MalformedCallback("click amount was not a number") from exc

        number = str(form.get("merchant_trans_id", "")).strip()
        external = str(form.get("click_trans_id", "")).strip()

        return CallbackRequest(
            provider=PROVIDER,
            command=command,
            correlation=external,
            number=InvoiceNumber(number) if number else None,
            external_id=ExternalId(external) if external else None,
            amount_minor=MinorUnits(int(amount)),
            cancel_reason=_int(form.get("error")) if command == CANCEL else None,
            raw=dict(form),
        )

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The flat object Click expects, for one decision."""
        base = _echo(request)
        if isinstance(outcome, Refused):
            return _body(
                base
                | {
                    "error": ERROR_CODES.get(outcome.reason, ERROR_CODES[INTERNAL]),
                    "error_note": ERROR_NOTES.get(
                        outcome.reason, ERROR_NOTES[INTERNAL]
                    ),
                }
            )
        if not isinstance(outcome, Settled):
            return _body(
                base
                | {
                    "error": ERROR_CODES[MALFORMED],
                    "error_note": ERROR_NOTES[MALFORMED],
                }
            )

        held = (
            "merchant_prepare_id"
            if request.command == CREATE
            else "merchant_confirm_id"
        )
        return _body(
            base
            | {
                held: _int(outcome.transaction.reference),
                "error": OK,
                "error_note": SUCCESS_NOTE,
            }
        )

    def refuse_unauthenticated(self, *, request: RawRequest) -> ProviderResponse:
        """Click's own code for a digest that did not match."""
        return _body(
            _echo_form(request.form)
            | {
                "error": ERROR_CODES[UNAUTHORIZED],
                "error_note": ERROR_NOTES[UNAUTHORIZED],
            }
        )

    def refuse_malformed(self, *, request: RawRequest) -> ProviderResponse:
        """A signed post this protocol cannot read - a version moved."""
        return _body(
            _echo_form(request.form)
            | {"error": ERROR_CODES[MALFORMED], "error_note": ERROR_NOTES[MALFORMED]}
        )

    def _command(self, *, form: Mapping[str, str]) -> Command:
        """Which of the three things this post is."""
        action = _int(form.get("action"))
        if action == ACTION_PREPARE:
            return CREATE
        if action == ACTION_COMPLETE:
            return CANCEL if _int(form.get("error")) < OK else PERFORM
        raise MalformedCallback(f"click sent an unknown action: {form.get('action')!r}")

    def _signature(self, *, form: Mapping[str, str], fields: tuple[str, ...]) -> str:
        """The digest Click computed, recomputed from what arrived."""
        parts: list[str] = []
        for field in fields:
            parts.append(str(form.get(field, "")))
            if field == SECRET_AFTER:
                parts.append(self._secret_key)
        return hashlib.md5("".join(parts).encode()).hexdigest()


def _echo(request: CallbackRequest) -> dict[str, Any]:
    """The two identifiers Click matches its own record against."""
    return {
        "click_trans_id": _int(request.correlation),
        "merchant_trans_id": request.number or "",
    }


def _echo_form(form: Mapping[str, str]) -> dict[str, Any]:
    """The same two, recovered from a post that was never parsed."""
    return {
        "click_trans_id": _int(form.get("click_trans_id")),
        "merchant_trans_id": str(form.get("merchant_trans_id", "")),
    }


def _body(payload: Mapping[str, Any]) -> ProviderResponse:
    return ProviderResponse(status_code=200, body=dict(payload))


def _int(value: Any) -> int:
    """A form field as an integer, or zero."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


__all__ = ["ORDER_PARAM", "PROVIDER", "ClickAdapter"]
