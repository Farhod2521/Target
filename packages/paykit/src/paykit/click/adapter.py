"""Click, as one :class:`~paykit.ports.PaymentPort`.

Click's SHOP-API is two form posts rather than a JSON-RPC conversation.
*Prepare* asks whether an invoice can be held; *Complete* says what became
of it. Both are signed with an MD5 digest over a fixed field order, and
both expect a flat JSON object back with an ``error`` number in it.

Three differences from the Payme side are worth knowing before reading.

**One endpoint serves both posts.** Click's cabinet asks for a Prepare URL
and a Complete URL, and the same address goes in both boxes: the
``action`` field already says which one this is, and two routes would be
two places to keep a signature check correct.

**A cancel arrives as a success.** Complete carries Click's own ``error``
field, and a negative value in it means the money did not move. It is
still a well-formed, correctly signed request that we answer 0 to - what
changed is which command the domain is given.

**Money is quoted in whole currency.** Click sends ``"49000.00"`` where
this system stores ``4900000``, and the digest is computed over the string
exactly as sent. So the amount is converted, and the *sent* form is what
gets hashed - never a re-rendered one.
"""

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

# The field Click's checkout page reads our invoice number out of, and the
# one it sends back as ``merchant_trans_id``.
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
        """Hold the shop's credentials and how its currency subdivides.

        ``decimal_places`` is here rather than on each call because it is a
        property of the deployment's currency, not of one invoice, and an
        adapter that had to be told it every time would eventually be told
        it wrong on the path that signs.

        Refuses to exist without the three credentials. A blank secret key
        makes every signature match nothing, which reads in a log as Click
        sending forgeries.
        """
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

    # --- Going out -------------------------------------------------------

    def checkout(self, *, request: CheckoutRequest) -> Checkout:
        """The checkout link, built offline.

        Query parameters rather than an encoded blob. ``decimal_places``
        comes from the request here rather than from the adapter: this is
        the amount a person will read on Click's own page, and it belongs
        to the invoice being paid.
        """
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

        # Encoded, because one of these values is a URL of ours and a
        # ``?`` or ``&`` inside it would end the query string early - which
        # sends the payer somewhere shorter than intended and drops the
        # rest of the parameters with it. ``:`` and ``/`` are left as they
        # are: both are legal in a query value, and escaping them makes a
        # link nobody can read in a log.
        query = urlencode(params, quote_via=quote, safe=":/")
        return Checkout(
            provider=PROVIDER, kind=REDIRECT, url=f"{self._checkout_url}?{query}"
        )

    # --- Coming in -------------------------------------------------------

    def authenticate(self, *, request: RawRequest) -> bool:
        """Whether the digest over this post matches our secret key.

        The field list depends on the step - Complete signs one field more
        than Prepare - so the action is read first. An action that is
        neither is not authenticated: there is no correct digest for a step
        that does not exist, and answering one would mean hashing whatever
        field list a stranger implied.

        :func:`hmac.compare_digest` for the comparison, as everywhere else
        a secret is checked: a plain ``==`` leaks how much of the digest
        was right through how long it took to say no.
        """
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
        """Read one post as a command about one invoice.

        The amount is converted from whole currency here and never later.
        A body whose amount is not a number at all is malformed rather than
        a mismatch: a mismatch is a number we disagree with, and reporting
        one for a body we could not read would send an operator looking for
        a tampered link that does not exist.
        """
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

    # --- Going back ------------------------------------------------------

    def render(self, *, request: CallbackRequest, outcome: Outcome) -> ProviderResponse:
        """The flat object Click expects, for one decision.

        Click never asks the two questions Payme does - what became of an
        attempt, and what happened in a window - so an outcome shaped like
        an answer to either of those cannot be expressed in this protocol.
        It is answered as a refusal rather than raised: the alternative is
        a 500 on a URL somebody's money is going through.
        """
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

        # Prepare is told what to remember; Complete is told what we
        # confirmed. The same value under two names, because Click stores
        # them in two columns and reconciles one against the other.
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
        """Click's own code for a digest that did not match.

        Still a 200. Click reads a non-2xx as an outage at our end and
        keeps the payment in limbo, which is worse for the payer than a
        clear refusal in the body.
        """
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

    # --- Internals -------------------------------------------------------

    def _command(self, *, form: Mapping[str, str]) -> Command:
        """Which of the three things this post is.

        Prepare is always a create. Complete is a perform or a cancel, and
        the field that decides is Click's own ``error`` - negative means
        the money did not move. Reading that field as merely informational
        is what leaves a subscription running on a payment that failed.
        """
        action = _int(form.get("action"))
        if action == ACTION_PREPARE:
            return CREATE
        if action == ACTION_COMPLETE:
            return CANCEL if _int(form.get("error")) < OK else PERFORM
        raise MalformedCallback(f"click sent an unknown action: {form.get('action')!r}")

    def _signature(self, *, form: Mapping[str, str], fields: tuple[str, ...]) -> str:
        """The digest Click computed, recomputed from what arrived.

        MD5 because the protocol says MD5. It is a shared-secret digest
        over a short fixed field list rather than a password hash, and the
        alternative to matching the provider is not authenticating at all.

        Values are taken verbatim from the form. Re-rendering the amount
        would change ``"49000.00"`` into ``"49000.0"`` on some paths and
        produce a digest that never matches.
        """
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
    """A form field as an integer, or zero.

    Zero rather than an exception. Every caller here is deciding what to
    echo or which branch to take, and both have a defined answer for a
    field that is missing - while a raise would turn a readable refusal
    into a stack trace on the payment path.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


__all__ = ["ORDER_PARAM", "PROVIDER", "ClickAdapter"]
