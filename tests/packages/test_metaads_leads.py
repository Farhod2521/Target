"""Reading a lead, sweeping for the ones a webhook lost, and subscribing.

The third is the one that costs everything when it is left out: a page
nobody subscribed collects forms and tells nobody, with no error to find.
"""

import json
from datetime import UTC, datetime

import httpx
import pytest
from adskit import ExternalRef, LeadSourcePort
from adskit.errors import AuthFailed
from metaads.adapter import MetaLeads, bundle
from metaads.client import GraphClient
from metaads.dto import LeadRow
from metaads.leads import LEAD_FIELDS, fetch_lead, list_leads, subscribe_page

LEAD = {
    "id": "9001",
    "created_time": "2026-02-02T02:40:00+0000",
    "field_data": [
        {"name": "full_name", "values": ["Aziz Karimov"]},
        {"name": "phone_number", "values": ["+998901234567"]},
        {"name": "qaysi_vaqt_qulay", "values": ["12:00"]},
    ],
    "form_id": "777",
    "campaign_id": "111",
    "adset_id": "333",
    "ad_id": "222",
    "is_organic": False,
}


def answering(payload: dict, *, seen: list[httpx.Request] | None = None) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- One lead ------------------------------------------------------------
def test_a_lead_comes_back_whole() -> None:
    seen: list[httpx.Request] = []

    row = fetch_lead(leadgen_id="9001", token="t", client=answering(LEAD, seen=seen))

    assert row.id == "9001"
    assert row.answer("full_name") == "Aziz Karimov"
    assert row.answer("phone_number") == "+998901234567"
    assert LEAD_FIELDS in seen[0].url.params.get("fields", "")


def test_a_question_the_form_did_not_ask_answers_empty() -> None:
    """The questions are the advertiser's, so any lookup can miss."""
    row = LeadRow.model_validate(LEAD)

    assert row.answer("email") == ""


def test_only_the_first_answer_is_taken() -> None:
    """A repeated answer is Meta echoing a field the person edited.
    Concatenating them produces a name that is two names; the whole list
    stays in field_data either way."""
    row = LeadRow.model_validate(
        LEAD | {"field_data": [{"name": "full_name", "values": ["Aziz", "Karimov"]}]}
    )

    assert row.answer("full_name") == "Aziz"


def test_the_graph_read_and_the_webhook_disagree_about_the_ad_sets_name() -> None:
    """``adset_id`` here, ``adgroup_id`` there. Both are read."""
    assert LeadRow.model_validate(LEAD).adset_external_id == "333"
    assert (
        LeadRow.model_validate({"id": "1", "adgroup_id": "333"}).adset_external_id
        == "333"
    )


# --- The sweep -----------------------------------------------------------
def test_the_sweep_asks_for_leads_after_a_moment_the_caller_chose() -> None:
    """A package with no clock cannot decide what "recently" means, and a
    filter Meta compares as text silently returns everything."""
    seen: list[httpx.Request] = []
    since = datetime(2026, 2, 1, tzinfo=UTC)

    list_leads(
        form_id="777", since=since, token="t", client=answering({"data": []}, seen=seen)
    )

    sent = json.loads(seen[0].url.params["filtering"])
    assert sent == [
        {
            "field": "time_created",
            "operator": "GREATER_THAN",
            "value": int(since.timestamp()),
        }
    ]


def test_a_narrowed_sweep_closes_the_window_as_well() -> None:
    """A form too deep for one read is read a day at a time, and a day has
    two ends. Both clauses go in the one list Meta takes."""
    seen: list[httpx.Request] = []
    since = datetime(2026, 2, 1, tzinfo=UTC)
    until = datetime(2026, 2, 2, tzinfo=UTC)

    list_leads(
        form_id="777",
        since=since,
        until=until,
        token="t",
        client=answering({"data": []}, seen=seen),
    )

    sent = json.loads(seen[0].url.params["filtering"])
    assert sent[1] == {
        "field": "time_created",
        "operator": "LESS_THAN",
        "value": int(until.timestamp()),
    }


def test_the_sweep_reads_every_page_of_what_it_finds() -> None:
    rows = list_leads(
        form_id="777",
        since=datetime(2026, 2, 1, tzinfo=UTC),
        token="t",
        client=answering({"data": [LEAD, LEAD | {"id": "9002"}]}),
    )

    assert [row.id for row in rows] == ["9001", "9002"]


# --- Subscribing ---------------------------------------------------------
def test_subscribing_asks_for_exactly_the_leadgen_field() -> None:
    """A page subscribed to everything except this one looks healthy and
    delivers no leads."""
    seen: list[httpx.Request] = []

    ok = subscribe_page(
        page_id="31415",
        token="page-token",
        client=answering({"success": True}, seen=seen),
        dry_run=False,
    )

    assert ok is True
    assert dict(httpx.QueryParams(seen[0].content.decode()))["subscribed_fields"] == (
        "leadgen"
    )


def test_a_rehearsed_subscription_never_reaches_meta() -> None:
    """It spends no money and that is not the line: the line is whether a
    call reaches a page we do not own."""
    seen: list[httpx.Request] = []

    assert subscribe_page(
        page_id="31415", token="t", client=answering({"success": True}, seen=seen)
    )
    assert seen == []


# --- Through the port ----------------------------------------------------
def test_the_adapter_satisfies_the_port() -> None:
    assert isinstance(MetaLeads(), LeadSourcePort)


def test_the_bundle_hands_over_a_real_leads_port_now() -> None:
    assert isinstance(bundle().leads, LeadSourcePort)
    assert type(bundle().leads).__name__ == "MetaLeads"


def test_the_domain_gets_attribution_and_the_answer_sheet_untouched() -> None:
    """``field_data`` is not parsed here. The questions are the
    advertiser's, and turning them into a name and a phone number needs the
    country the business operates in - which this package cannot know."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("metaads.adapter.GraphClient", lambda **_: answering(LEAD))
        dto = MetaLeads().fetch_lead(
            ref=ExternalRef(provider="meta", level="form", id="9001"), token="t"
        )

    assert dto.adset_external_id == "333"
    assert dto.campaign_external_id == "111"
    assert dto.form is not None
    assert dto.form.id == "777"
    assert dto.field_data[0] == {"name": "full_name", "values": ["Aziz Karimov"]}
    assert dto.is_organic is False


def test_a_lead_meta_did_not_timestamp_arrives_without_one() -> None:
    """Not stamped with now. A port holds no clock, and a lead stamped with
    the moment a worker reached it arrived at the wrong time forever."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "metaads.adapter.GraphClient",
            lambda **_: answering({"id": "9001", "form_id": "777"}),
        )
        dto = MetaLeads().fetch_lead(
            ref=ExternalRef(provider="meta", level="form", id="9001"), token="t"
        )

    assert dto.submitted_at is None


def test_metas_refusal_arrives_as_the_domains_own() -> None:
    """A service catching ``code == 190`` is one that breaks the day Google
    is added."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Invalid OAuth access token"}}
        )

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with (
        pytest.MonkeyPatch.context() as patch,
        pytest.raises(AuthFailed),
    ):
        patch.setattr("metaads.adapter.GraphClient", lambda **_: client)
        MetaLeads().fetch_lead(
            ref=ExternalRef(provider="meta", level="form", id="9001"), token="t"
        )
