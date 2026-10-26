"""Lead forms and leads, as Meta answers them."""

from datetime import datetime
from typing import Any, Final

from pydantic import Field, field_validator

from metaads.dto_base import MetaDTO, _text

# The one lead-form status this product acts on. Everything else Meta may
# answer means "not collecting" - see :attr:`LeadFormRow.is_collecting`.
_FORM_ACTIVE: Final = "ACTIVE"


class LeadFormRow(MetaDTO):
    """One row of ``/{page_id}/leadgen_forms``.

    The read that keeps a form's row true. Without it a form is written
    down once, when a launch creates it, and never asked about again - so
    an advertiser who archives it in Ads Manager leaves this product
    sweeping a form that collects nothing, and a form they build by hand
    collects leads that arrive with no row to attach them to.

    ``leads_count`` is Meta's own total for the form, and it is the only
    external check this product has on whether it holds every lead it was
    sent. The webhook leaves no trace when it fails; this number does.

    ``status`` is kept exactly as it arrives and is deliberately **not**
    enumerated here. Meta answers ``ACTIVE`` for a form that is collecting
    and one of several other words for one that is not, and the full set is
    not something this package has seen - so the string travels whole and
    the domain asks the only question it has a use for, which is
    :attr:`is_collecting`.
    """

    id: str
    name: str = ""
    status: str = ""
    # Absent on some forms rather than zero, which is why it is nullable:
    # "Meta did not say" and "nobody has filled this in" lead to opposite
    # decisions about whether to go looking for leads.
    leads_count: int | None = None
    created_time: datetime | None = None
    questions: tuple[dict[str, Any], ...] = ()
    # A plain string on the read. ``privacy_policy`` is the name the
    # *create* call takes, and Meta does not answer it when asked for -
    # reading it made every form look as if it linked to no policy.
    privacy_policy_url: str = ""
    # Where a form built in Ads Manager keeps its policy link instead:
    # ``{"privacy_policy": {"url": ...}}``, with the string above left
    # empty. Read through :attr:`policy_url`.
    legal_content: dict[str, Any] = Field(default_factory=dict)
    thank_you_page: dict[str, Any] = Field(default_factory=dict)
    locale: str = ""

    @field_validator("privacy_policy_url", mode="before")
    @classmethod
    def _url_or_empty(cls, value: object) -> str:
        """An address that is not a string is no address, not an error."""
        return _text(value)

    @field_validator("legal_content", mode="before")
    @classmethod
    def _node_or_empty(cls, value: object) -> object:
        """A node that is not an object is no node - and failing the parse
        would lose the page's whole form list, not just this link."""
        return value if isinstance(value, dict) else {}

    @property
    def policy_url(self) -> str:
        """The form's privacy link, wherever Meta put it, or empty.

        Either place is the form's own link. An empty answer here hides
        the form from the picker, so missing the one Meta filled in is
        the costly mistake, not reading both.
        """
        policy = self.legal_content.get("privacy_policy")
        nested = _text(policy.get("url")) if isinstance(policy, dict) else ""
        return self.privacy_policy_url.strip() or nested.strip()

    @property
    def is_collecting(self) -> bool:
        """Whether this form is still taking answers.

        The one question the domain asks of a form's state, and the only
        one that can be answered without knowing Meta's whole vocabulary:
        ``ACTIVE`` collects, and everything else - archived, deleted,
        paused, draft - does not. An unfamiliar word therefore reads as
        "not collecting", which is the safe direction: the cost is a sweep
        that does not happen, against leads fetched from a form nobody is
        running.
        """
        return self.status.strip().upper() == _FORM_ACTIVE

    @property
    def thank_you_button(self) -> str:
        """Meta's ``button_type`` for the screen after the form, upper-cased.

        Empty when Meta did not say - a form read without the thank-you
        fields expanded, or one built with no thank-you screen at all.
        """
        return _text(self.thank_you_page.get("button_type")).upper()

    @property
    def thank_you_target(self) -> str:
        """Where that button goes: the address, or the number it dials."""
        return _text(self.thank_you_page.get("website_url")) or _text(
            self.thank_you_page.get("business_phone_number")
        )

    @property
    def thank_you_button_text(self) -> str:
        return _text(self.thank_you_page.get("button_text"))


class LeadRow(MetaDTO):
    """One row of ``/{leadgen_id}`` or ``/{form_id}/leads``.

    ``field_data`` is the answer sheet and stays exactly as it arrived. The
    questions are chosen per form by the advertiser, so no fixed set of
    columns can hold them, and a shape invented here would be one more
    thing to migrate the first time somebody adds a question.

    Meta sends it as a list of ``{"name": ..., "values": [...]}``. Both the
    key and the plural are load-bearing: ``name`` is the *question's* key
    rather than the person's name, and a question can have several answers.

    ``is_organic`` is Meta's word for a lead that came through the form
    without an ad behind it - somebody who found the page. It is not the
    same as a test lead and is kept apart from one.
    """

    id: str
    created_time: datetime | None = None
    field_data: tuple[dict[str, Any], ...] = ()
    form_id: str = ""
    campaign_id: str = ""
    # Meta's own inconsistency: the webhook calls it ``adgroup_id`` and the
    # Graph read calls it ``adset_id``. Both are accepted so one model can
    # parse either, and :attr:`adset_external_id` is what callers read.
    adset_id: str = ""
    adgroup_id: str = ""
    ad_id: str = ""
    is_organic: bool = False

    @property
    def adset_external_id(self) -> str:
        """Whichever of Meta's two names for the same id came back."""
        return self.adset_id or self.adgroup_id

    def answer(self, key: str) -> str:
        """The first answer to one question, or an empty string.

        First and not joined: a repeated answer is Meta echoing a field the
        person edited, and concatenating them produces a name that is two
        names. The whole list stays in ``field_data`` either way.
        """
        for row in self.field_data:
            if row.get("name") != key:
                continue
            values = row.get("values")
            if isinstance(values, list) and values:
                return str(values[0]).strip()
        return ""


class ConversionReceiptRow(MetaDTO):
    """What Meta answers after a batch of lead verdicts has been posted.

    Three fields and only the first is load-bearing.
    ``events_received`` is Meta's own count of what it took, and it is the
    only number that may be trusted: a batch of forty can answer thirty-one
    when nine of the leads have aged past the dataset's window, with a 200
    and no error anywhere. A caller that assumed "posted" meant "counted"
    would stamp all forty as reported and never send the nine again.

    ``fbtrace_id`` is kept for the reason a customer list keeps its session
    id: a conversation with support about a figure that does not match
    needs something to quote.

    Named a receipt rather than a result because that is what it is. Nothing
    was created, nothing can be read back, and the only evidence the events
    ever existed is this count and, eventually, a number in Events Manager.
    """

    events_received: int = 0
    messages: tuple[str, ...] = ()
    fbtrace_id: str = ""
