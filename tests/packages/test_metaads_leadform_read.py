"""Reading back the form a lead came through.

Without this read a form is written down once - when a launch makes it -
and never asked about again, so nothing here knows when one is archived,
and a form built by hand in Ads Manager is invisible along with the leads
it collects.

What is pinned below is the awkward half of Meta's answer: a status
vocabulary this package deliberately does not enumerate, a privacy policy
nested a level down, and a lead count whose *absence* means something
different from its being zero.

No network: every payload is served through a mock transport.
"""

from contextlib import nullcontext

import httpx
import pytest
from adskit import ExternalRef
from metaads.adapter import MetaLeads
from metaads.client import GraphClient
from metaads.dto import LeadFormRow
from metaads.leadforms import FORM_FIELDS, list_forms

FORM = {
    "id": "777",
    "name": "Osh markazi - lidlar",
    "status": "ACTIVE",
    "leads_count": 42,
    "created_time": "2026-01-15T10:30:00+0500",
    "questions": [
        {"type": "FULL_NAME", "key": "full_name"},
        {"type": "PHONE", "key": "phone_number"},
        {"type": "CUSTOM", "key": "q3", "label": "Qaysi tumandasiz?"},
    ],
    "privacy_policy_url": "https://targetolog.ai/privacy",
    "thank_you_page": {"title": "Rahmat"},
    "locale": "uz_UZ",
}


def answering(payload: dict, *, seen: list[httpx.Request] | None = None) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- What is asked for ---------------------------------------------------
def test_the_fields_that_make_the_read_worth_making_are_asked_for() -> None:
    """Meta's default answer to this edge is an id and a name, neither of
    which says whether the form is still collecting."""
    seen: list[httpx.Request] = []

    list_forms(page_id="31415", token="t", client=answering({}, seen=seen))

    url = str(seen[0].url)
    for field in ("status", "leads_count", "questions", "privacy_policy_url"):
        assert field in url


def test_it_reads_the_page_and_not_the_ad_account() -> None:
    """A lead form is a page object. The account's token is refused here
    with a permission error naming the form rather than the reason."""
    seen: list[httpx.Request] = []

    list_forms(page_id="31415", token="t", client=answering({}, seen=seen))

    assert "31415/leadgen_forms" in str(seen[0].url)
    assert FORM_FIELDS in str(seen[0].url.params.get("fields", ""))


# --- What comes back -----------------------------------------------------
def test_a_form_comes_back_parsed() -> None:
    rows = list_forms(page_id="31415", token="t", client=answering({"data": [FORM]}))

    assert rows[0].id == "777"
    assert rows[0].name == "Osh markazi - lidlar"
    assert rows[0].leads_count == 42
    assert rows[0].created_time is not None
    assert len(rows[0].questions) == 3


def test_the_privacy_policy_url_is_read_as_meta_answers_it() -> None:
    """A plain string. ``privacy_policy`` is the create parameter, and a
    read asking for it gets nothing back - every form then looked like one
    linking to no policy and dropped out of the picker."""
    assert LeadFormRow.model_validate(FORM).privacy_policy_url == (
        "https://targetolog.ai/privacy"
    )


@pytest.mark.parametrize(
    "policy",
    [
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param({"url": "https://x"}, id="not-a-string"),
    ],
)
def test_an_unreadable_privacy_policy_is_empty_rather_than_an_error(
    policy: object,
) -> None:
    """A form this product did not create can carry anything here, and a
    form list that fails to parse is a page whose leads stop being found."""
    row = LeadFormRow.model_validate({"id": "9", "privacy_policy_url": policy})

    assert row.privacy_policy_url == ""


def test_a_form_built_in_ads_manager_has_its_policy_under_legal_content() -> None:
    """Ads Manager leaves the plain string empty and nests the link. Read
    only from the string, such a form looked policy-less and was hidden."""
    row = LeadFormRow.model_validate(
        {
            "id": "9",
            "privacy_policy_url": "",
            "legal_content": {
                "id": "55",
                "privacy_policy": {"url": "https://shop.uz/privacy"},
            },
        }
    )

    assert row.policy_url == "https://shop.uz/privacy"


def test_the_plain_string_wins_when_both_are_there() -> None:
    row = LeadFormRow.model_validate(
        {
            "id": "9",
            "privacy_policy_url": "https://a.uz/p",
            "legal_content": {"privacy_policy": {"url": "https://b.uz/p"}},
        }
    )

    assert row.policy_url == "https://a.uz/p"


@pytest.mark.parametrize(
    "legal",
    [
        pytest.param({}, id="absent"),
        pytest.param(None, id="null"),
        pytest.param("55", id="an-id-alone"),
        pytest.param({"id": "55"}, id="bare-node"),
        pytest.param({"privacy_policy": "https://x"}, id="not-a-node"),
        pytest.param({"privacy_policy": {"url": 7}}, id="not-a-string"),
    ],
)
def test_an_unreadable_legal_content_is_no_policy(legal: object) -> None:
    row = LeadFormRow.model_validate({"id": "9", "legal_content": legal})

    assert row.policy_url == ""


def test_the_nested_policy_is_asked_for_inside_its_node() -> None:
    """Named bare, ``legal_content`` comes back as an id and nothing else."""
    assert "legal_content{privacy_policy{url}}" in FORM_FIELDS


# --- The status vocabulary -----------------------------------------------
def test_active_is_the_only_word_that_means_collecting() -> None:
    assert LeadFormRow.model_validate({"id": "9", "status": "ACTIVE"}).is_collecting


@pytest.mark.parametrize(
    "status", ["ARCHIVED", "DELETED", "PAUSED", "DRAFT", "", "SOMETHING_NEW"]
)
def test_every_other_word_means_not_collecting(status: str) -> None:
    """Meta's full set is not enumerated anywhere here, deliberately: this
    package has not seen all of it, and a word it has never met must read
    as "not collecting" rather than as an unhandled state.

    The safe direction, and it is worth naming which one that is: the cost
    of being wrong here is a sweep that does not happen, against fetching
    leads from a form nobody is running.
    """
    assert not LeadFormRow.model_validate({"id": "9", "status": status}).is_collecting


def test_the_provider_word_survives_into_the_domain_object() -> None:
    """Two fields and not one. The domain acts on the boolean; an operator
    holding this against Meta's own screen needs Meta's own word."""
    dto = MetaLeads._form(LeadFormRow.model_validate({"id": "9", "status": "PAUSED"}))

    assert dto.is_collecting is False
    assert dto.status_raw == "PAUSED"


# --- Absent is not zero --------------------------------------------------
def test_a_form_meta_gave_no_count_for_says_so_rather_than_zero() -> None:
    """The distinction the sweep reads. Zero means nobody filled this form
    in, so asking for its leads is a call that cannot return any; ``None``
    means nobody has asked, and those are the forms most likely to be
    collecting right now.
    """
    assert LeadFormRow.model_validate({"id": "9"}).leads_count is None
    assert LeadFormRow.model_validate({"id": "9", "leads_count": 0}).leads_count == 0


def test_the_whole_form_crosses_the_boundary_as_a_domain_object() -> None:
    dto = MetaLeads._form(LeadFormRow.model_validate(FORM))

    assert dto.ref.id == "777"
    assert dto.ref.level == "form"
    assert dto.is_collecting is True
    assert dto.leads_count == 42
    assert dto.privacy_policy_url == "https://targetolog.ai/privacy"
    assert dto.locale == "uz_UZ"
    assert len(dto.questions_raw) == 3


def test_the_port_answers_through_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end through the class the registry hands out.

    The adapter opens its own connection, so what is replaced here is the
    session it opens - the same seam every other port method is exercised
    through.
    """
    page = ExternalRef(provider="meta", level="page", id="31415")
    graph = answering({"data": [FORM]})
    monkeypatch.setattr("metaads.adapter.session", lambda _token: nullcontext(graph))

    forms = MetaLeads().list_forms(page=page, token="t")

    assert [form.ref.id for form in forms] == ["777"]
    assert forms[0].is_collecting is True


# --- The screen after the form -------------------------------------------
def test_the_thank_you_fields_are_asked_for_inside_the_node() -> None:
    """A node named bare comes back as its id; the button is inside it."""
    assert "thank_you_page{" in FORM_FIELDS
    for field in ("button_type", "website_url", "business_phone_number"):
        assert field in FORM_FIELDS


@pytest.mark.parametrize(
    ("page", "kind", "target"),
    [
        ({"button_type": "NONE"}, "none", ""),
        (
            {"button_type": "VIEW_WEBSITE", "website_url": "https://t.me/osh"},
            "website",
            "https://t.me/osh",
        ),
        (
            {"button_type": "CALL_BUSINESS", "business_phone_number": "+998901234567"},
            "call",
            "+998901234567",
        ),
        ({"button_type": "DOWNLOAD", "button_text": "Yuklab olish"}, "other", ""),
        ({"title": "Rahmat"}, "", ""),
    ],
)
def test_the_ending_crosses_in_the_domain_words(
    page: dict, kind: str, target: str
) -> None:
    row = LeadFormRow.model_validate({"id": "9", "thank_you_page": page})

    dto = MetaLeads._form(row)

    assert dto.ending_kind == kind
    assert dto.ending_target == target


def test_the_button_words_come_across_as_written() -> None:
    row = LeadFormRow.model_validate(
        {
            "id": "9",
            "thank_you_page": {"button_type": "VIEW_WEBSITE", "button_text": "Sayt"},
        }
    )

    assert MetaLeads._form(row).ending_button_text == "Sayt"
