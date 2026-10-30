"""Creating objects at Meta, and the three ways that goes quietly wrong.

No network anywhere: every payload is served through a mock transport, and
the most important test in the file asserts that a dry run never reaches
that transport at all.

What is pinned here is the awkward half of writing to Graph. Nested values
have to be JSON and not Python reprs. An empty field is not the same as an
absent one, except for the one list that has to be sent empty. And a
targeting spec can be accepted, trimmed, and answered with 200 - which is
why an ad set reads its own work back.
"""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.specs import (
    BID_COST_CAP,
    BID_LOWEST_COST,
    CTA_NO_BUTTON,
    STATUS_PAUSED,
    AdSetSpec,
    CampaignSpec,
    CreativeSpec,
)
from metaads.stories import story_spec
from metaads.writes import (
    changed_from,
    create_ad,
    create_adset,
    create_campaign,
    delete_object,
    dropped_from,
    read_targeting,
    set_status,
    write_targeting,
)
from metaads.writing import id_of, is_dry_run_id
from pydantic import ValidationError

# Somewhere outside Meta. Every creative needs one - see the rule pinned
# further down - and the value itself never matters to these tests.
SITE = "https://targetolog.ai/"

TARGETING: dict[str, Any] = {
    "geo_locations": {"cities": [{"key": "2019233", "radius": 12}]},
    "age_min": 25,
    "age_max": 45,
    "flexible_spec": [{"interests": [{"id": "6003", "name": "Coffee"}]}],
}

CAMPAIGN = CampaignSpec(name="Osh markazi", objective="OUTCOME_LEADS")

ADSET = AdSetSpec(
    name="Toshkent 25-45",
    campaign_id="120210",
    daily_budget_minor=50_000,
    optimization_goal="LEAD_GENERATION",
    billing_event="IMPRESSIONS",
    targeting=TARGETING,
)


def recording(
    payload: dict[str, Any] | None = None,
    *,
    on_get: dict[str, Any] | None = None,
) -> tuple[GraphClient, list[httpx.Request]]:
    """A client that answers everything and keeps what it was asked."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET" and on_get is not None:
            return httpx.Response(200, json=on_get)
        return httpx.Response(200, json=payload or {"id": "1"})

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, seen


def exploding() -> GraphClient:
    """A client that fails the test if anything is sent through it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a dry run reached the network: {request.url}")

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def sent(request: httpx.Request) -> dict[str, str]:
    return {key: value[0] for key, value in parse_qs(request.content.decode()).items()}


# --- Nothing is sent unless it was asked for -----------------------------
def test_a_dry_run_never_reaches_the_network() -> None:
    """The whole safety property, asserted rather than described.

    Every write defaults to dry_run=True, and the check lives one line
    above the HTTP call so that a new code path cannot get past it.
    """
    graph = exploding()

    create_campaign(account_id="act_1", spec=CAMPAIGN, token="t", client=graph)
    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph)
    create_ad(
        account_id="act_1",
        adset_id="1",
        creative_id="2",
        name="x",
        token="t",
        client=graph,
    )
    set_status(object_id="1", status="ACTIVE", token="t", client=graph)
    delete_object(object_id="1", token="t", client=graph)


def test_a_dry_run_id_says_what_it_is() -> None:
    """Meta's ids are decimal digits, so this can never collide with one."""
    created = create_campaign(account_id="act_1", spec=CAMPAIGN, token="t")

    assert is_dry_run_id(created)
    assert not is_dry_run_id("120210000000000")


def test_a_real_delete_refuses_to_send_a_dry_run_id() -> None:
    """The failure this guard exists for: a rollback walking the refs of a
    launch that only ever ran as a rehearsal."""
    graph = exploding()

    assert delete_object(
        object_id="dryrun-campaign", token="t", client=graph, dry_run=False
    )


# --- What a write actually puts in the body ------------------------------
def test_a_campaign_is_created_paused() -> None:
    graph, seen = recording()

    create_campaign(
        account_id="act_1", spec=CAMPAIGN, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["status"] == STATUS_PAUSED


def test_the_special_ad_category_field_is_sent_even_when_empty() -> None:
    """Meta reads a missing one as an error rather than as "none of them"."""
    graph, seen = recording()

    create_campaign(
        account_id="act_1", spec=CAMPAIGN, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["special_ad_categories"] == "[]"
    assert "special_ad_category_country" not in sent(seen[0])


def test_a_category_is_sent_with_the_countries_it_runs_in() -> None:
    """Left out, Meta takes the account's tax country - often never set."""
    graph, seen = recording()

    create_campaign(
        account_id="act_1",
        spec=CAMPAIGN.model_copy(
            update={
                "special_ad_categories": ("HOUSING",),
                "special_ad_category_country": ("UZ",),
            }
        ),
        token="t",
        client=graph,
        dry_run=False,
    )

    assert sent(seen[0])["special_ad_category_country"] == '["UZ"]'


def test_budget_sharing_is_answered_rather_than_left_out() -> None:
    """Meta refuses a campaign that carries no budget of its own without an
    explicit yes or no here, and says only "Invalid parameter" about it."""
    graph, seen = recording()

    create_campaign(
        account_id="act_1", spec=CAMPAIGN, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["is_adset_budget_sharing_enabled"] == "false"


def test_a_false_is_a_word_meta_knows_and_not_pythons() -> None:
    """A form post turns ``False`` into "False", which Meta reads as a word
    rather than as a boolean - and rejects, naming a field that was filled
    in as far as the caller could tell."""
    graph, seen = recording()

    create_campaign(
        account_id="act_1",
        spec=CAMPAIGN.model_copy(update={"budget_sharing": True}),
        token="t",
        client=graph,
        dry_run=False,
    )

    assert sent(seen[0])["is_adset_budget_sharing_enabled"] == "true"


def test_the_bid_strategy_is_named_rather_than_inherited() -> None:
    """Meta refuses an ad set whose strategy implies a number nobody sent,
    and the refusal names the bid field rather than the inheritance."""
    graph, seen = recording()

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    assert sent(seen[0])["bid_strategy"] == BID_LOWEST_COST


def test_an_uncapped_adset_carries_no_bid_amount_at_all() -> None:
    """A zero here is a cap of nothing, not the absence of one.

    ``post_object`` drops ``None``, ``""`` and ``{}`` and keeps everything
    else on purpose - an empty ``special_ad_categories`` and a ``false``
    budget-sharing answer are both things Meta requires - so a plain zero
    survives and would go out as ``bid_amount=0`` on every ad set nobody
    capped. The spec's own validator guarantees the pairing: zero here
    means the strategy is uncapped, and an uncapped ad set must not carry
    the key.
    """
    graph, seen = recording(on_get={"targeting": TARGETING})

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    assert "bid_amount" not in sent(seen[0])


def test_an_adset_with_no_end_sends_none() -> None:
    """An empty string is an error where an absent field is "runs on"."""
    graph, seen = recording(on_get={"targeting": TARGETING})

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    assert "end_time" not in sent(seen[0])


def test_an_adset_that_stops_says_when() -> None:
    graph, seen = recording(on_get={"targeting": TARGETING})
    ending = ADSET.model_copy(update={"end_time": "2026-10-01T23:59:00+05:00"})

    create_adset(
        account_id="act_1", spec=ending, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["end_time"] == "2026-10-01T23:59:00+05:00"


def test_a_capped_adset_still_carries_its_cap() -> None:
    """The other half. Dropping the field when it is meant would leave a
    capped strategy with no amount, which Meta rejects one call into the
    sequence with a rollback to run."""
    graph, seen = recording(on_get={"targeting": TARGETING})
    capped = ADSET.model_copy(
        update={"bid_strategy": BID_COST_CAP, "bid_amount_minor": 250}
    )

    create_adset(
        account_id="act_1", spec=capped, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["bid_amount"] == "250"


def test_nested_values_go_out_as_json_and_not_as_a_python_repr() -> None:
    """A dict passed straight through becomes "{'age_min': 25}" - single
    quotes - and Meta rejects it naming the field and not the reason."""
    graph, seen = recording(on_get={"targeting": TARGETING})

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    assert '"age_min": 25' in sent(seen[0])["targeting"]


def test_a_field_nobody_filled_in_is_left_out_rather_than_sent_blank() -> None:
    """An empty start_time is a validation error; a missing one means the
    ad set starts when it is switched on."""
    graph, seen = recording(on_get={"targeting": TARGETING})

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    body = sent(seen[0])
    assert "start_time" not in body
    assert "promoted_object" not in body


def test_an_ad_names_its_creative_the_way_meta_wants() -> None:
    graph, seen = recording()

    create_ad(
        account_id="act_1",
        adset_id="2301",
        creative_id="555",
        name="Reklama",
        token="t",
        client=graph,
        dry_run=False,
    )

    assert sent(seen[0])["creative"] == '{"creative_id": "555"}'


def test_a_write_that_returns_no_id_is_a_failure() -> None:
    """Accepted and unreferenceable. Recorded as success it would fail at
    the next step with nothing pointing back at the cause."""
    graph, _ = recording({"success": True})

    with pytest.raises(MetaAPIError):
        create_campaign(
            account_id="act_1", spec=CAMPAIGN, token="t", client=graph, dry_run=False
        )


def test_a_delete_uses_the_delete_verb() -> None:
    graph, seen = recording({"success": True})

    delete_object(object_id="120210", token="t", client=graph, dry_run=False)

    assert seen[0].method == "DELETE"


# --- What Meta quietly did not keep --------------------------------------
def test_the_ad_set_reads_its_own_targeting_back() -> None:
    graph, seen = recording(on_get={"targeting": TARGETING})

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    assert [request.method for request in seen] == ["POST", "GET"]


def test_an_interest_meta_dropped_is_reported() -> None:
    """One id missing out of several is invisible at the top level, and is
    the difference between the audience approved and the one bought."""
    returned = {**TARGETING, "flexible_spec": [{"interests": []}]}
    graph, _ = recording(on_get={"targeting": returned})

    created = create_adset(
        account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False
    )

    assert created.dropped["interests"] == ["6003"]


def test_a_placement_meta_removed_is_reported() -> None:
    sent_spec = {**TARGETING, "instagram_positions": ["explore_home"]}

    assert dropped_from(sent=sent_spec, returned=TARGETING) == {
        "instagram_positions": ["explore_home"]
    }


def test_meta_rewriting_what_it_kept_is_not_reported_as_a_loss() -> None:
    """Meta expands a city key into a full location object on every ad set.
    Reported as a difference, this would be noise within a week."""
    returned = {
        **TARGETING,
        "geo_locations": {"cities": [{"key": "2019233", "name": "Tashkent"}]},
    }

    assert dropped_from(sent=TARGETING, returned=returned) == {}


def test_a_field_meta_added_is_reported_as_changed() -> None:
    """An ad set sent without an age ceiling comes back with one."""
    sent_spec = {key: value for key, value in TARGETING.items() if key != "age_max"}

    assert changed_from(sent=sent_spec, returned=TARGETING) == {
        "age_max": {"sent": None, "returned": 45}
    }


def test_a_plain_value_meta_reset_is_reported_and_a_rewritten_list_is_not() -> None:
    returned = {
        **TARGETING,
        "age_min": 18,
        "geo_locations": {"cities": [{"key": "2019233", "name": "Tashkent"}]},
    }

    assert changed_from(sent=TARGETING, returned=returned) == {
        "age_min": {"sent": 25, "returned": 18}
    }


def test_the_ad_set_keeps_the_targeting_meta_returned() -> None:
    returned = {**TARGETING, "age_max": 65}
    graph, _ = recording(on_get={"targeting": returned})

    created = create_adset(
        account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False
    )

    assert created.returned == returned


def test_a_dry_run_ad_set_reports_nothing_dropped() -> None:
    created = create_adset(account_id="act_1", spec=ADSET, token="t")

    assert created.dropped == {}


# --- The creative's two vocabularies -------------------------------------
def test_an_image_creative_calls_the_headline_name() -> None:
    """Meta's word. A creative built with "headline" is accepted and shows
    an empty headline."""
    spec = CreativeSpec(
        name="c",
        page_id="99",
        message="Salom",
        headline="Bugun",
        image_hash="abc",
        link_url=SITE,
    )

    block = story_spec(spec)["link_data"]

    assert block["name"] == "Bugun"
    assert block["image_hash"] == "abc"


def test_a_video_creative_calls_the_same_thing_title() -> None:
    spec = CreativeSpec(
        name="c",
        page_id="99",
        message="Salom",
        headline="Bugun",
        description="Qisqa",
        video_id="777",
        thumbnail_url="https://x/t.jpg",
        link_url=SITE,
    )

    block = story_spec(spec)["video_data"]

    assert block["title"] == "Bugun"
    assert block["link_description"] == "Qisqa"
    assert block["image_url"] == "https://x/t.jpg"


def test_a_video_with_no_button_carries_no_link_description() -> None:
    """Meta refuses the pair: ``100/1815614``, seen in production."""
    spec = CreativeSpec(
        name="c",
        page_id="99",
        message="Salom",
        description="Qisqa",
        video_id="777",
        thumbnail_url="https://x/t.jpg",
        link_url=SITE,
        call_to_action=CTA_NO_BUTTON,
    )

    block = story_spec(spec)["video_data"]

    assert "link_description" not in block
    assert "call_to_action" not in block


def test_a_lead_ad_button_carries_the_form_and_not_a_link() -> None:
    """Both would open a website instead of the form it was built for."""
    spec = CreativeSpec(
        name="c",
        page_id="99",
        message="Salom",
        image_hash="abc",
        lead_form_id="777",
        link_url=SITE,
    )

    action = story_spec(spec)["link_data"]["call_to_action"]

    assert action["value"] == {"lead_gen_form_id": "777"}


def test_the_link_is_the_one_it_was_given() -> None:
    """Meta requires a link even where it will never be followed, and a
    link built from the page id is the one address it will not take."""
    spec = CreativeSpec(
        name="c", page_id="99", message="Salom", image_hash="abc", link_url=SITE
    )

    assert story_spec(spec)["link_data"]["link"] == SITE


@pytest.mark.parametrize(
    "link",
    [
        pytest.param("https://www.facebook.com/1305481949308392", id="page"),
        pytest.param("https://facebook.com/somebusiness", id="no-www"),
        pytest.param("https://m.facebook.com/somebusiness", id="mobile"),
        pytest.param("https://www.instagram.com/somebusiness", id="instagram"),
        pytest.param("", id="empty"),
    ],
)
def test_a_lead_creative_refuses_a_link_that_stays_inside_meta(link: str) -> None:
    """100/1815316, and it arrives after the form nothing can delete.

    Refused at construction instead, where it costs one exception and no
    provider objects at all.
    """
    with pytest.raises(ValidationError):
        CreativeSpec(
            name="c",
            page_id="99",
            message="Salom",
            image_hash="abc",
            lead_form_id="777",
            link_url=link,
        )


@pytest.mark.parametrize(
    "link",
    [
        pytest.param("https://targetolog.ai/", id="ours"),
        pytest.param("https://somebusiness.uz/menu", id="the-advertiser-s"),
        pytest.param("https://not-facebook.com/x", id="merely-similar"),
    ],
)
def test_a_lead_creative_takes_a_link_that_leaves_meta(link: str) -> None:
    spec = CreativeSpec(
        name="c",
        page_id="99",
        message="Salom",
        image_hash="abc",
        lead_form_id="777",
        link_url=link,
    )

    assert story_spec(spec)["link_data"]["link"] == link


def test_an_ad_with_no_form_may_still_link_to_a_page() -> None:
    """The rule is Meta's and it is about lead ads. A package three other
    projects use must not invent a wider one."""
    spec = CreativeSpec(
        name="c",
        page_id="99",
        message="Salom",
        image_hash="abc",
        link_url="https://www.facebook.com/99",
    )

    assert story_spec(spec)["link_data"]["call_to_action"]["value"] == {
        "link": "https://www.facebook.com/99"
    }


def test_a_blank_line_is_left_out_of_the_story_spec() -> None:
    """An empty description renders as a blank row on some placements."""
    spec = CreativeSpec(
        name="c", page_id="99", message="Salom", image_hash="abc", link_url=SITE
    )

    assert "description" not in story_spec(spec)["link_data"]


# --- When Meta answers 200 and says nothing ------------------------------
# The one failure in this package with no Meta error behind it: no code, no
# subcode, no message. What came back is the whole of the evidence, so it
# travels with the refusal - the alternative is a launch that failed after
# creating a form nothing can delete, and no way at all to learn why.
def test_a_create_that_returns_no_id_says_what_it_did_return() -> None:
    with pytest.raises(MetaAPIError) as caught:
        id_of({"success": True, "message": "queued"})

    assert "queued" in str(caught.value)
    assert "success" in str(caught.value)


def test_a_bare_true_is_recognisable_in_the_refusal() -> None:
    """``_decode`` wraps a non-object answer as ``{"result": ...}``. Without
    the body in the message that shape is indistinguishable from an empty
    one."""
    with pytest.raises(MetaAPIError) as caught:
        id_of({"result": True})

    assert "result" in str(caught.value)


def test_nothing_secret_shaped_is_repeated_back() -> None:
    """The message is written to an audit row a person reads."""
    with pytest.raises(MetaAPIError) as caught:
        id_of({"access_token": "EAAG-real-token", "note": "x"})

    assert "EAAG-real-token" not in str(caught.value)
    assert "***" in str(caught.value)


def test_a_long_body_is_cut_rather_than_dropped() -> None:
    with pytest.raises(MetaAPIError) as caught:
        id_of({"data": "x" * 2000})

    message = str(caught.value)
    assert "xxxx" in message
    assert "chars)" in message


def test_an_id_that_is_there_is_returned_unchanged() -> None:
    assert id_of({"id": "120210123"}) == "120210123"


# --- The controls a media buyer reaches for ------------------------------
def test_an_adset_with_no_window_lets_meta_choose_one() -> None:
    """An empty list is an answer Meta refuses, not the absence of one."""
    graph, seen = recording(on_get={"targeting": TARGETING})

    create_adset(account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False)

    assert "attribution_spec" not in sent(seen[0])
    assert "frequency_control_specs" not in sent(seen[0])


def test_an_adset_that_names_its_window_sends_metas_own_shape() -> None:
    graph, seen = recording(on_get={"targeting": TARGETING})
    windowed = ADSET.model_copy(
        update={
            "attribution": ({"event_type": "CLICK_THROUGH", "window_days": 1},),
        }
    )

    create_adset(
        account_id="act_1", spec=windowed, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["attribution_spec"] == (
        '[{"event_type": "CLICK_THROUGH", "window_days": 1}]'
    )


def test_a_campaign_with_no_ceiling_carries_none() -> None:
    """A zero here is a cap of nothing, the same trap the bid amount has."""
    graph, seen = recording()

    create_campaign(
        account_id="act_1", spec=CAMPAIGN, token="t", client=graph, dry_run=False
    )

    assert "spend_cap" not in sent(seen[0])


def test_a_campaign_that_names_a_ceiling_sends_it() -> None:
    graph, seen = recording()
    capped = CAMPAIGN.model_copy(update={"spend_cap_minor": 500_000})

    create_campaign(
        account_id="act_1", spec=capped, token="t", client=graph, dry_run=False
    )

    assert sent(seen[0])["spend_cap"] == "500000"


def test_an_ad_set_keeps_its_id_when_the_read_back_is_braked() -> None:
    """The write's own answer can pass 80% of the call budget, and the brake
    then refuses the read-back. Raised, that lost the only copy of the id
    of an ad set Meta had already made."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        if request.method == "GET":
            raise AssertionError("the brake should have stopped the read")
        return httpx.Response(
            200,
            json={"id": "120"},
            headers={"x-app-usage": '{"call_count": 95}'},
        )

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    created = create_adset(
        account_id="act_1", spec=ADSET, token="t", client=graph, dry_run=False
    )

    assert created.id == "120"
    assert created.dropped == {}
    assert seen == ["POST"]


# --- Replacing a running audience ----------------------------------------
def test_a_replaced_audience_reports_what_meta_holds_afterwards() -> None:
    """The mirror keeps this, so the screen shows the audience that runs,
    not the one that was sent."""
    returned = {
        **TARGETING,
        "geo_locations": {"cities": [{"key": "2019233", "name": "Tashkent"}]},
        "flexible_spec": [{"interests": []}],
    }
    graph, seen = recording(on_get={"targeting": returned})

    written = write_targeting(
        object_id="120", targeting=TARGETING, token="t", client=graph, dry_run=False
    )

    assert [request.method for request in seen] == ["POST", "GET"]
    assert written.returned == returned
    assert written.dropped["interests"] == ["6003"]


def test_a_dry_run_audience_write_reaches_nothing_and_holds_nothing() -> None:
    written = write_targeting(
        object_id="120", targeting=TARGETING, token="t", client=exploding()
    )

    assert written.returned == {} and written.dropped == {}


def test_the_audience_is_read_as_meta_holds_it() -> None:
    graph, seen = recording(on_get={"targeting": TARGETING})

    assert read_targeting(object_id="120", token="t", client=graph) == TARGETING
    assert [request.method for request in seen] == ["GET"]


def test_a_failed_read_before_a_write_raises_rather_than_answering_empty() -> None:
    """Empty would read as "nothing to protect" and let the write through."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "down", "code": 2}})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(MetaAPIError):
        read_targeting(object_id="120", token="t", client=graph)
