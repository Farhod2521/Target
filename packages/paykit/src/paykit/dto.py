"""What crosses the boundary, in both directions."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from paykit.refs import (
    CheckoutKind,
    Command,
    ExternalId,
    InvoiceNumber,
    MinorUnits,
    ProviderName,
    Refusal,
    TransactionState,
)


class Frozen(BaseModel):
    """Immutable, and strict about types it was not given."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CheckoutRequest(Frozen):
    """Everything an adapter needs to build a payment page link.

    ``amount_minor`` is in the *invoice's* currency, and ``decimal_places``
    says how many of those units make one whole one. The second is here
    rather than looked up because this package holds no currency table:
    duplicating one is how two copies end up disagreeing about a currency,
    and the caller already knows the answer.

    ``return_url`` is where the provider sends the payer afterwards. It is
    a courtesy and never the thing that settles a payment - the callback
    is - so an adapter whose provider ignores it drops it without
    complaint.
    """

    number: InvoiceNumber
    amount_minor: MinorUnits
    decimal_places: int = Field(ge=0, le=4)
    return_url: str = ""
    language: str = ""
    currency: str = ""
    description: str = ""
    ttl_seconds: int | None = Field(default=None, ge=1)


class Checkout(Frozen):
    """Where the payer goes, or what the payer types.

    Two shapes, because two shapes exist in this market. A card provider
    hands over a URL. An agent network hands over a *reference* - a number
    the payer enters into a terminal or an app, at a counter, with cash -
    and there is no page to redirect to at all.

    One DTO rather than two ports. The difference is what the screen
    renders, not what the domain does: both end in the same callback and
    the same invoice, and a second port would make every caller ask which
    kind it was holding before it could ask anything else.
    """

    provider: ProviderName
    kind: CheckoutKind
    url: str = ""
    reference: str = ""


class RawRequest(Frozen):
    """One HTTP request from a provider, as it arrived.

    Bytes rather than a parsed body, and that is load-bearing: a signature
    is computed over what was actually sent, and re-serialised JSON has a
    different key order and therefore a different digest.

    ``form`` is filled for providers that post form-encoded fields and
    empty for the ones that post JSON. Both are here because the port must
    accept either without the view knowing which - the view holds a
    provider name and a request, and asking it to choose how to read the
    body would put a provider's shape in the web layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    headers: Mapping[str, str] = Field(default_factory=dict)
    body: bytes = b""
    form: Mapping[str, str] = Field(default_factory=dict)


class CallbackRequest(Frozen):
    """One provider request, read as a command about one invoice.

    ``correlation`` is whatever the provider needs echoed back - a JSON-RPC
    ``id``, a transaction number - and is opaque to the domain. It is
    carried on the request rather than dug back out of ``raw`` at render
    time so that a reply cannot be built without it.

    ``requested_at`` is the provider's own timestamp for the event, not
    ours. It is data, and the difference between it and when the row was
    written is what a slow night looks like afterwards.
    """

    provider: ProviderName
    command: Command
    correlation: str = ""

    number: InvoiceNumber | None = None
    external_id: ExternalId | None = None
    amount_minor: MinorUnits | None = None
    requested_at: datetime | None = None

    cancel_reason: int | None = None

    window_start: datetime | None = None
    window_end: datetime | None = None

    raw: Mapping[str, object] = Field(default_factory=dict)


class TransactionRecord(Frozen):
    """One payment attempt, as the domain holds it.

    Three identifiers, and each answers a different party's question.
    ``number`` is the invoice, which is what a person reads out to support.
    ``external_id`` is the provider's own id for the attempt, which is what
    a callback names. ``reference`` is ours for the attempt, which is what
    the provider stores and reconciles against - Payme calls it
    ``transaction`` in every reply and Click calls it
    ``merchant_prepare_id``.

    ``reference`` is digits, and that is not cosmetic: one of the two
    providers here stores it in an integer column, and a value it cannot
    hold comes back mangled on the request that settles the money.

    ``requested_at`` is the provider's own clock for when the payer began,
    where the provider sends one. ``created_at`` is when the row was
    written. They are minutes apart on a slow night and a statement
    reconciles against the first.
    """

    number: InvoiceNumber
    reference: str
    external_id: ExternalId
    state: TransactionState
    amount_minor: MinorUnits
    created_at: datetime
    requested_at: datetime | None = None
    performed_at: datetime | None = None
    canceled_at: datetime | None = None
    cancel_reason: int | None = None


class Allowed(Frozen):
    """The answer to ``check``: this invoice may be paid.

    Empty on purpose. A provider that wants detail on a payable invoice -
    a description, a line item - gets it from the adapter, which is where
    that provider's vocabulary lives.
    """


class Settled(Frozen):
    """The answer to ``create``, ``perform``, ``cancel`` and ``status``.

    One class for four commands because the provider wants the same thing
    back from all of them: what state the attempt is in now, and when it
    got there. A class per command would be four names for one shape.
    """

    transaction: TransactionRecord


class Statement(Frozen):
    """The answer to ``statement``: every attempt in the window."""

    transactions: Sequence[TransactionRecord] = ()


class Refused(Frozen):
    """The answer when the request is understood and will not be honoured.

    ``detail`` is for the operator and the log, never for the payer: it may
    name a field or an amount, and it goes into the provider's own error
    body where only the provider reads it.
    """

    reason: Refusal
    detail: str = ""


Outcome = Allowed | Settled | Statement | Refused


class ProviderResponse(Frozen):
    """The HTTP answer, ready for the view to return.

    The status code is the adapter's decision and it is rarely 4xx. Both
    protocols here carry their failures *inside* a 200 body - a non-2xx is
    read as "your endpoint is broken" and, at Payme, as grounds to stop
    sending - so the one place a code other than 200 is right is a request
    that did not authenticate at all.
    """

    status_code: int = 200
    body: Mapping[str, object] = Field(default_factory=dict)


__all__ = [
    "Allowed",
    "CallbackRequest",
    "Checkout",
    "CheckoutRequest",
    "Outcome",
    "ProviderResponse",
    "RawRequest",
    "Refused",
    "Settled",
    "Statement",
    "TransactionRecord",
]
