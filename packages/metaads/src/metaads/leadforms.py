"""The lead form: the object the whole product is built around.

Every other thing created here exists to put this in front of somebody. It
is also the only one created on the **page** rather than on the ad account,
and therefore the only one that needs the page token - the user token gets
an error naming a permission rather than the object, which reads like a
missing scope and is not one.

Two of Meta's rules are worth knowing before reading the code:

* A **privacy policy URL is mandatory.** Meta refuses the form without it,
  and it is refused after the campaign and ad set exist. Required at
  construction instead, in :class:`metaads.specs.LeadFormSpec`.
* A **standard question carries no label.** ``FULL_NAME`` and ``PHONE`` are
  prefilled from the person's own profile and labelled in their own
  language; sending our Uzbek wording alongside is an error, not an
  override.
"""

from typing import Any, Final
from urllib.parse import urlencode

from metaads.client import GraphClient
from metaads.dto import LeadFormRow
from metaads.parsing import parsed_all
from metaads.specs import (
    QUESTION_CUSTOM,
    THANK_YOU_CALL,
    THANK_YOU_NONE,
    THANK_YOU_WEBSITE,
    LeadFormSpec,
    LeadQuestionSpec,
)
from metaads.writing import fake_id, graph_client, id_of, post_object

_FORM: Final = "form"

# Shown beside the privacy link on the form itself. Uzbek, because the
# people reading it are the advertiser's customers - the one string in this
# package that reaches a person rather than a log.
_PRIVACY_LINK_TEXT: Final = "Maxfiylik siyosati"


# What a form says about itself. Asked for explicitly, because Meta's
# default answer to this edge is an id and a name - neither of which says
# whether the form is still collecting.
#
# ``leads_count`` is the field worth the call on its own: it is Meta's own
# total, and the only number this product can check its own count against.
# A webhook that was never delivered leaves nothing behind, so a difference
# here is the only evidence that one went missing.
#
# ``questions`` rides along rather than being read per form. A form's
# questions cannot be edited - Meta refuses, and a change means a new form
# - so this is not a field that drifts; it is a field this product simply
# never had for a form it did not create itself.
#
# ``thank_you_page`` and ``legal_content`` are nodes of their own, and a
# node named bare comes back as its id and nothing else - so the fields
# wanted from them are asked for inside them.
FORM_FIELDS: Final = (
    "id,name,status,leads_count,created_time,questions,privacy_policy_url,"
    "legal_content{privacy_policy{url}},"
    "thank_you_page{title,body,button_type,button_text,website_url,"
    "business_phone_number},locale"
)

# Meta's own maximum for this edge. A page with four hundred forms is a
# page that has been running lead ads for years, and it still comes back in
# a handful of requests.
PAGE_SIZE: Final = 100


def list_forms(
    *, page_id: str, token: str, client: GraphClient | None = None
) -> list[LeadFormRow]:
    """Every lead form on this page, whatever state it is in.

    The **page's** token, like everything else about a form. A lead form
    is not an ad-account object: it lives on the page, and the ad account's
    token is refused here with a permission error that names the form
    rather than the reason.

    Archived and deleted forms come back too, and are wanted. A form that
    stopped collecting still holds the leads it collected, and the row
    describing it is what makes those leads readable a year later - so the
    caller marks such a form rather than forgetting it.
    """
    with graph_client(client, token) as graph:
        rows = graph.get_all(
            f"{page_id}/leadgen_forms", fields=FORM_FIELDS, limit=PAGE_SIZE
        )
    return parsed_all(LeadFormRow, rows)


def create_lead_form(
    *,
    page_id: str,
    spec: LeadFormSpec,
    page_token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create the form on the page.

    ``page_token`` is named rather than called ``token`` so that passing
    the wrong one is visible at the call site. The two are both strings and
    both valid; only one of them works here.
    """
    if dry_run:
        return fake_id(_FORM)

    payload = post_object(
        path=f"{page_id}/leadgen_forms",
        data={
            "name": spec.name,
            "questions": questions_for(spec.questions),
            "privacy_policy": {
                "url": spec.privacy_policy_url,
                "link_text": _PRIVACY_LINK_TEXT,
            },
            "thank_you_page": _thank_you(spec),
            "locale": spec.locale,
            # Meta's own word for the confirmation screen. Sent only when
            # asked for: the field's absence is the ordinary form, and
            # sending ``false`` where Meta expects nothing is one more
            # thing for it to disagree with.
            "is_optimized_for_quality": spec.higher_intent or None,
        },
        token=page_token,
        client=client,
    )
    return id_of(payload)


def questions_for(specs: tuple[LeadQuestionSpec, ...]) -> list[dict[str, Any]]:
    """Meta's question list, with keys it can refer to answers by.

    The keys are generated here and are positional - ``q1``, ``q2`` - which
    is deliberate. They come back on every lead as the name of the field
    that was answered, so they have to be stable for the life of the form,
    and a key derived from Uzbek label text would change the moment somebody
    fixed a typo in the question.
    """
    built: list[dict[str, Any]] = []

    for index, question in enumerate(specs, start=1):
        if not question.is_custom:
            built.append({"type": question.kind.upper()})
            continue

        row: dict[str, Any] = {
            "type": QUESTION_CUSTOM,
            "key": f"q{index}",
            "label": question.label,
        }
        if question.options:
            row["options"] = [
                {"key": f"q{index}_o{choice}", "value": value}
                for choice, value in enumerate(question.options, start=1)
            ]
        built.append(row)

    return built


def _thank_you(spec: LeadFormSpec) -> dict[str, Any]:
    """The screen somebody sees after answering, or nothing at all.

    Omitted entirely when there is no text for it. An empty thank-you page
    is not the same as no thank-you page: Meta renders the first as a blank
    screen and falls back to its own wording for the second.

    ``button_type`` is sent even when it is ``NONE``: Meta requires the
    field, and a business with nowhere to send somebody is an ordinary case
    here. Each button carries only its own field - an address beside a
    call button is one more thing for Meta to disagree with.
    """
    if not (spec.thank_you_title or spec.thank_you_body):
        return {}

    button = spec.thank_you_type
    page: dict[str, Any] = {
        "title": spec.thank_you_title,
        "body": spec.thank_you_body,
        "button_type": button,
    }
    if button != THANK_YOU_NONE:
        page["button_text"] = spec.thank_you_button_text
    if button == THANK_YOU_WEBSITE:
        page["website_url"] = spec.thank_you_url
    if button == THANK_YOU_CALL:
        page["business_phone_number"] = spec.thank_you_phone
        page["country_code"] = spec.thank_you_country

    return {key: value for key, value in page.items() if value != ""}


# Where a page owner agrees to Meta's lead-ad terms. Not an API call - it is
# a URL handed to a browser, like the OAuth dialog, and it lives here
# because a lead form is exactly what it unblocks.
TERMS_URL: Final = "https://www.facebook.com/ads/leadgen/tos"


def terms_url(page_id: str = "") -> str:
    """The terms page, for one page when we know which.

    The id matters more than it looks. Acceptance is per page, and an
    advertiser with four pages who opens the bare URL agrees on whichever
    one Meta picks for them - then tries again, gets the same refusal, and
    has no way to tell that they agreed to the wrong thing.
    """
    if not page_id:
        return TERMS_URL
    return f"{TERMS_URL}?{urlencode({'page_id': page_id})}"
