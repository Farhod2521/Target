"""The lead form: the object the whole product is built around."""

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

_PRIVACY_LINK_TEXT: Final = "Maxfiylik siyosati"


FORM_FIELDS: Final = (
    "id,name,status,leads_count,created_time,questions,privacy_policy_url,"
    "legal_content{privacy_policy{url}},"
    "thank_you_page{title,body,button_type,button_text,website_url,"
    "business_phone_number},locale"
)

PAGE_SIZE: Final = 100


def list_forms(
    *, page_id: str, token: str, client: GraphClient | None = None
) -> list[LeadFormRow]:
    """Every lead form on this page, whatever state it is in."""
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
    """Create the form on the page."""
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
            "is_optimized_for_quality": spec.higher_intent or None,
        },
        token=page_token,
        client=client,
    )
    return id_of(payload)


def questions_for(specs: tuple[LeadQuestionSpec, ...]) -> list[dict[str, Any]]:
    """Meta's question list, with keys it can refer to answers by."""
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
    """The screen somebody sees after answering, or nothing at all."""
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


TERMS_URL: Final = "https://www.facebook.com/ads/leadgen/tos"


def terms_url(page_id: str = "") -> str:
    """The terms page, for one page when we know which."""
    if not page_id:
        return TERMS_URL
    return f"{TERMS_URL}?{urlencode({'page_id': page_id})}"
