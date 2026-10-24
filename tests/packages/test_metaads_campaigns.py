"""Reading an ad account's objects, and what Meta's shapes actually are.

No network: every payload here is the shape Meta's own documentation
describes, served through a mock transport. What is being pinned is the
awkward half of that shape - budgets that arrive as strings, a learning
stage nested one level down, a lead form id buried four levels inside a
creative - because each of those is a place where a plausible-looking
parse is silently wrong.
"""

import httpx
import pytest
from metaads.campaigns import (
    MIRROR_PAGES,
    count_campaign_adsets,
    list_ads,
    list_adsets,
    list_campaigns,
)
from metaads.client import MAX_PAGES, GraphClient, PagesExhausted
from metaads.dto import AdRow, AdSetRow, CampaignRow

CAMPAIGN = {
    "id": "120210",
    "name": "Osh markazi - lidlar",
    "objective": "OUTCOME_LEADS",
    "status": "ACTIVE",
    "effective_status": "ACTIVE",
    "daily_budget": "1000",
    "special_ad_categories": ["NONE"],
    "created_time": "2026-01-15T10:30:00+0500",
}

ADSET = {
    "id": "2301",
    "name": "Toshkent 25-45",
    "campaign_id": "120210",
    "status": "ACTIVE",
    "effective_status": "CAMPAIGN_PAUSED",
    "optimization_goal": "LEAD_GENERATION",
    "billing_event": "IMPRESSIONS",
    "destination_type": "ON_AD",
    "daily_budget": "500",
    "targeting": {"geo_locations": {"cities": [{"key": "2019233"}]}},
    "promoted_object": {"page_id": "99"},
    "learning_stage_info": {"status": "LEARNING", "attribution_windows": ["7d_click"]},
    "start_time": "2026-01-16T00:00:00+0500",
}

AD = {
    "id": "3401",
    "name": "Video reklama",
    "adset_id": "2301",
    "status": "ACTIVE",
    "effective_status": "DISAPPROVED",
    "creative": {
        "id": "555",
        "object_story_spec": {
            "page_id": "99",
            "link_data": {
                "call_to_action": {
                    "type": "SIGN_UP",
                    "value": {"lead_gen_form_id": "777"},
                }
            },
        },
    },
}


def graph_returning(payload: dict, capture: list[httpx.Request] | None = None):
    """A GraphClient answering every request with one recorded body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- What is asked for ---------------------------------------------------
def test_the_fields_that_decide_delivery_are_asked_for() -> None:
    """Meta's default field set is id and name, and says nothing useful."""
    seen: list[httpx.Request] = []

    list_campaigns(account_id="act_1", token="t", client=graph_returning({}, seen))

    url = str(seen[0].url)
    assert "effective_status" in url
    assert "daily_budget" in url


def test_the_learning_stage_is_asked_for_on_ad_sets() -> None:
    """The guardrail reads it. Without it every ad set looks safe to touch."""
    seen: list[httpx.Request] = []

    list_adsets(account_id="act_1", token="t", client=graph_returning({}, seen))

    assert "learning_stage_info" in str(seen[0].url)


def test_the_creative_is_asked_for_so_the_lead_form_can_be_found() -> None:
    seen: list[httpx.Request] = []

    list_ads(account_id="act_1", token="t", client=graph_returning({}, seen))

    assert "object_story_spec" in str(seen[0].url)


# --- How deep a list reads ---------------------------------------------
def graph_paging(pages: int | None) -> GraphClient:
    """A GraphClient serving one ad set per page, ``pages`` deep.

    ``None`` never stops: every page names a next one, which is what a
    list longer than any ceiling looks like from here.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("p", "1"))
        body: dict = {"data": [{**ADSET, "id": f"s{page}"}]}
        if pages is None or page < pages:
            body["paging"] = {
                "next": f"https://graph.facebook.com/v26.0/act_1/adsets?p={page + 1}"
            }
        return httpx.Response(200, json=body)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_a_list_deeper_than_the_clients_default_is_read_whole() -> None:
    """An account with years of ad sets behind it pages past 25.

    The mirror deletes whatever the list leaves out, so a list cut at the
    client's default is not a shorter sync - it is a refused one, every
    time, and nothing from the account reaches the screens.
    """
    deeper = MAX_PAGES + 5

    rows = list_adsets(account_id="act_1", token="t", client=graph_paging(deeper))

    assert len(rows) == deeper


def test_the_lists_still_stop_at_a_ceiling_of_their_own() -> None:
    """Deeper, not bottomless: a cursor pointing at itself still ends."""
    with pytest.raises(PagesExhausted) as caught:
        list_adsets(account_id="act_1", token="t", client=graph_paging(None))

    assert caught.value.pages == MIRROR_PAGES


# --- Campaigns -----------------------------------------------------------
def test_a_campaign_comes_back_parsed() -> None:
    rows = list_campaigns(
        account_id="act_1", token="t", client=graph_returning({"data": [CAMPAIGN]})
    )

    assert rows[0].id == "120210"
    assert rows[0].objective == "OUTCOME_LEADS"
    assert rows[0].created_time is not None


def test_a_budget_string_becomes_minor_units() -> None:
    """Meta sends "1000" and means ten dollars, not a thousand."""
    row = CampaignRow.model_validate(CAMPAIGN)

    assert row.daily_budget_minor == 1000


def test_an_absent_budget_is_none_and_not_zero() -> None:
    """Null means the budget lives one level down. Zero would mean broke."""
    row = CampaignRow.model_validate({"id": "1"})

    assert row.daily_budget_minor is None


def test_a_field_meta_adds_later_does_not_break_the_parse() -> None:
    """extra="ignore": a new key must not take an account's sync down."""
    row = CampaignRow.model_validate({**CAMPAIGN, "brand_new_field": {"x": 1}})

    assert row.id == "120210"


# --- Ad sets -------------------------------------------------------------
def test_the_learning_stage_is_flattened_to_a_string() -> None:
    """Callers should read a status, not walk a dict that may be absent."""
    row = AdSetRow.model_validate(ADSET)

    assert row.learning_status == "LEARNING"


def test_a_missing_learning_stage_reads_as_empty() -> None:
    """Normal for an ad set that never delivered. Not an error."""
    row = AdSetRow.model_validate({"id": "1"})

    assert row.learning_status == ""


def test_targeting_is_kept_in_metas_own_shape() -> None:
    """Parsing it into columns would freeze today's answer into the schema."""
    row = AdSetRow.model_validate(ADSET)

    assert row.targeting["geo_locations"]["cities"][0]["key"] == "2019233"


def test_an_end_time_that_was_never_set_is_none() -> None:
    row = AdSetRow.model_validate(ADSET)

    assert row.start_time is not None
    assert row.end_time is None


# --- Ads -----------------------------------------------------------------
def test_the_lead_form_is_dug_out_of_the_creative() -> None:
    """The link between an ad and the leads it bought - all of CPQL."""
    row = AdRow.model_validate(AD)

    assert row.lead_form_external_id == "777"
    assert row.creative_external_id == "555"


def test_a_video_creative_hides_the_form_under_a_different_key() -> None:
    payload = {
        "id": "2",
        "creative": {
            "id": "9",
            "object_story_spec": {
                "video_data": {"call_to_action": {"value": {"lead_gen_form_id": "888"}}}
            },
        },
    }

    assert AdRow.model_validate(payload).lead_form_external_id == "888"


@pytest.mark.parametrize(
    "creative",
    [
        pytest.param({}, id="no-creative"),
        pytest.param({"id": "9"}, id="no-story-spec"),
        pytest.param({"id": "9", "object_story_spec": {"page_id": "1"}}, id="no-cta"),
        pytest.param(
            {"id": "9", "object_story_spec": {"link_data": {"message": "hi"}}},
            id="cta-without-form",
        ),
    ],
)
def test_an_ad_that_collects_no_leads_has_no_form(creative: dict) -> None:
    """Most ads on most accounts. An empty answer is normal, not a failure."""
    row = AdRow.model_validate({"id": "2", "creative": creative})

    assert row.lead_form_external_id == ""


def test_an_ad_is_parsed_from_the_list() -> None:
    rows = list_ads(
        account_id="act_1", token="t", client=graph_returning({"data": [AD]})
    )

    assert rows[0].adset_id == "2301"
    assert rows[0].effective_status == "DISAPPROVED"


# --- What Meta says is wrong --------------------------------------------
ISSUE = {
    "level": "AD_SET",
    "error_code": 1815869,
    "error_summary": "Ad Set May Get Zero Impressions",
    "error_message": "Your audience is too small to deliver.",
    "error_type": "DELIVERY",
}

ADVICE = {
    "code": 1815203,
    "title": "Widen your audience",
    "message": "Adding interests could reach more people.",
    "importance": "HIGH",
    "confidence": "MEDIUM",
    "blame_field": "targeting",
}

REJECTION = {
    "global": {"Personal Attributes": "Ads must not imply personal traits."},
    "placement_specific": {"instagram": {"Adult Content": "Not allowed here."}},
}


def test_the_diagnostics_are_asked_for_on_every_level() -> None:
    """The first thing a media buyer looks at.

    A campaign can be ACTIVE, funded and spending nothing because of one
    row in ``issues_info``, and the advertiser's only clue is a figure that
    does not move.
    """
    for reader in (list_campaigns, list_adsets, list_ads):
        seen: list[httpx.Request] = []
        reader(account_id="act_1", token="t", client=graph_returning({}, seen))
        assert "issues_info" in str(seen[0].url), reader.__name__


def test_advice_is_asked_for_where_there_is_something_to_advise() -> None:
    """Campaigns and ad sets hold audiences and budgets. An ad holds
    neither, so Meta has nothing to suggest about one."""
    for reader in (list_campaigns, list_adsets):
        seen: list[httpx.Request] = []
        reader(account_id="act_1", token="t", client=graph_returning({}, seen))
        assert "recommendations" in str(seen[0].url), reader.__name__

    seen = []
    list_ads(account_id="act_1", token="t", client=graph_returning({}, seen))
    assert "recommendations" not in str(seen[0].url)


def test_the_review_verdict_is_asked_for_on_ads() -> None:
    seen: list[httpx.Request] = []

    list_ads(account_id="act_1", token="t", client=graph_returning({}, seen))

    assert "ad_review_feedback" in str(seen[0].url)


def test_an_issue_comes_back_parsed() -> None:
    rows = list_adsets(
        account_id="act_1",
        token="t",
        client=graph_returning({"data": [ADSET | {"issues_info": [ISSUE]}]}),
    )

    issue = rows[0].issues_info[0]
    assert issue.error_code == 1815869
    assert issue.error_summary == "Ad Set May Get Zero Impressions"
    assert issue.level == "AD_SET"


def test_an_object_with_nothing_wrong_carries_an_empty_list() -> None:
    """The ordinary answer. Meta omits the field rather than sending []."""
    rows = list_campaigns(
        account_id="act_1", token="t", client=graph_returning({"data": [CAMPAIGN]})
    )

    assert rows[0].issues_info == ()
    assert rows[0].recommendations == ()


def test_advice_comes_back_parsed() -> None:
    rows = list_campaigns(
        account_id="act_1",
        token="t",
        client=graph_returning({"data": [CAMPAIGN | {"recommendations": [ADVICE]}]}),
    )

    advice = rows[0].recommendations[0]
    assert advice.title == "Widen your audience"
    assert advice.importance == "HIGH"


def test_a_rejection_is_read_out_of_a_reserved_word() -> None:
    """Meta calls the key ``global``, which Python will not accept as a
    field name. The model reads it under another name."""
    rows = list_ads(
        account_id="act_1",
        token="t",
        client=graph_returning({"data": [AD | {"ad_review_feedback": REJECTION}]}),
    )

    feedback = rows[0].ad_review_feedback
    assert feedback is not None
    assert feedback.overall["Personal Attributes"].startswith("Ads must not")
    assert feedback.placement_specific["instagram"]["Adult Content"]


def test_an_ad_nobody_refused_has_no_verdict() -> None:
    """Most ads. Absent is the normal case, not a missing field."""
    rows = list_ads(
        account_id="act_1", token="t", client=graph_returning({"data": [AD]})
    )

    assert rows[0].ad_review_feedback is None


# --- How many groups one campaign holds ----------------------------------
def test_a_campaign_counts_the_groups_still_in_it() -> None:
    """Deleted and archived groups take no room in the campaign."""
    seen: list[httpx.Request] = []
    body = {
        "data": [
            {"id": "1", "effective_status": "ACTIVE"},
            {"id": "2", "effective_status": "PAUSED"},
            {"id": "3", "effective_status": "DELETED"},
            {"id": "4", "effective_status": "ARCHIVED"},
            {"id": "5", "effective_status": "CAMPAIGN_PAUSED"},
        ]
    }

    held = count_campaign_adsets(
        campaign_id="120210", token="t", client=graph_returning(body, seen)
    )

    assert held == 3
    assert "/120210/adsets" in str(seen[0].url)
