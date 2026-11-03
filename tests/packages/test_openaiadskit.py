"""openaiadskit: the client, its refusals, the ports and one campaign's launch."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from adskit import CampaignControlPort, ConnectPort, MetricsPort
from adskit.errors import AuthFailed, InvalidRequest, NotFound, RateLimited
from adskit.refs import ExternalRef
from openaiadskit import PROVIDER, AdsClient, read_ad_account
from openaiadskit.adapter import _PROVIDER, bundle
from openaiadskit.campaigns import OpenAICampaigns, campaign_found
from openaiadskit.client import BASE_URL
from openaiadskit.connect import KeyConnect
from openaiadskit.errors import OpenAIAdsAPIError, OpenAIAdsError
from openaiadskit.launch import (
    ChatCardSpec,
    ImageSpec,
    campaign_body,
    create_chat_campaign,
)
from openaiadskit.metrics import OpenAIMetrics
from openaiadskit.rows import (
    Locations,
    Place,
    delivery_of,
    locations_of,
    micros_to_minor,
    minor_to_micros,
)
from openaiadskit.translate import translate_error

Handler = Callable[[httpx.Request], httpx.Response]
KEY = "sk-ads-test"
ACCOUNT = ExternalRef(provider="chatgpt", level="account", id="adacct_1")
CAMPAIGN = ExternalRef(provider="chatgpt", level="campaign", id="cmpn_1")
AD_ACCOUNT = {
    "id": "adacct_1",
    "name": "Gul do'koni",
    "url": "https://gul.uz",
    "preview_url": None,
    "status": "active",
    "timezone": "Asia/Tashkent",
    "currency_code": "USD",
    "review": {"status": "approved"},
}


class Wire:
    """A fake OpenAI: answers by ``(method, path)`` and remembers every request."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path.removeprefix("/v1/")
        answer = self.routes.get((request.method, path))
        if answer is None:
            return httpx.Response(404, json={"error": {"message": "no such thing"}})
        if callable(answer):
            return answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path.removeprefix('/v1/')}" for r in self.seen]

    def body(self, method: str, path: str) -> dict[str, Any]:
        for request in self.seen:
            if (request.method, request.url.path) == (method, f"/v1/{path}"):
                return dict(json.loads(request.content))
        raise AssertionError(f"{method} {path} was not sent")


def _page(*rows: dict[str, Any], more: bool = False) -> dict[str, Any]:
    return {
        "object": "list",
        "data": list(rows),
        "first_id": rows[0]["id"] if rows else None,
        "last_id": rows[-1]["id"] if rows else None,
        "has_more": more,
    }


def _campaign(cid: str, status: str = "active", **extra: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "name": f"Kampaniya {cid}",
        "status": status,
        "created_at": 1777075200,
        "budget": {"daily_spend_limit_micros": 5_000_000},
        "bidding_type": "clicks",
        "serving_issues": [],
    } | extra


# --- The client -----------------------------------------------------------


def test_every_call_carries_the_key_as_a_bearer() -> None:
    wire = Wire({("GET", "ad_account"): AD_ACCOUNT})

    with AdsClient(api_key=KEY, http=wire.http()) as client:
        account = read_ad_account(client)

    assert wire.seen[0].headers["Authorization"] == f"Bearer {KEY}"
    assert str(wire.seen[0].url).startswith(BASE_URL)
    assert (account.id, account.currency, account.timezone) == (
        "adacct_1",
        "USD",
        "Asia/Tashkent",
    )
    assert account.review_status == "approved"


def test_the_key_stays_out_of_the_repr() -> None:
    assert KEY not in repr(AdsClient(api_key=KEY))


def test_pages_are_walked_by_their_cursor() -> None:
    def campaigns(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        if after is None:
            return httpx.Response(200, json=_page(_campaign("c1"), more=True))
        assert after == "c1"
        return httpx.Response(200, json=_page(_campaign("c2")))

    wire = Wire({("GET", "campaigns"): campaigns})
    with AdsClient(api_key=KEY, http=wire.http()) as client:
        found = [row["id"] for row in client.pages("campaigns")]

    assert found == ["c1", "c2"]
    assert wire.seen[0].url.params["limit"] == "500"


def test_lists_go_as_bracketed_repeats() -> None:
    wire = Wire({("GET", "campaigns"): _page()})
    with AdsClient(api_key=KEY, http=wire.http()) as client:
        list(client.pages("campaigns", {"include": ["serving_issues"]}))

    assert parse_qs(wire.seen[0].url.query.decode())["include[]"] == ["serving_issues"]


def test_a_create_carries_its_idempotency_key() -> None:
    wire = Wire({("POST", "campaigns"): {"id": "c1"}})
    with AdsClient(api_key=KEY, http=wire.http()) as client:
        client.post("campaigns", {"name": "x"}, idempotency_key="launch-1:campaign")

    assert wire.seen[0].headers["Idempotency-Key"] == "launch-1:campaign"


def test_a_refusal_keeps_what_openai_said() -> None:
    refused = httpx.Response(
        400,
        json={
            "error": {
                "message": "title too long",
                "code": "invalid_value",
                "param": "title",
            }
        },
        headers={"x-request-id": "req_9"},
    )
    wire = Wire({("POST", "ads"): refused})

    with (
        pytest.raises(OpenAIAdsAPIError) as caught,
        AdsClient(api_key=KEY, http=wire.http()) as client,
    ):
        client.post("ads", {})

    assert (caught.value.code, caught.value.param) == ("invalid_value", "title")
    assert caught.value.request_id == "req_9"
    assert str(caught.value) == "title too long"


def test_a_dead_network_is_not_sent() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with (
        pytest.raises(OpenAIAdsError),
        AdsClient(
            api_key=KEY, http=httpx.Client(transport=httpx.MockTransport(down))
        ) as client,
    ):
        client.get("ad_account")
    assert translate_error(OpenAIAdsError("x")).retryable


# --- Refusals in the domain's words --------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, AuthFailed), (404, NotFound), (422, InvalidRequest), (400, InvalidRequest)],
)
def test_statuses_become_domain_errors(status: int, expected: type) -> None:
    translated = translate_error(OpenAIAdsAPIError("x", http_status=status, code="c"))

    assert isinstance(translated, expected)
    assert translated.key == "chatgpt:c"


def test_a_rate_limit_carries_its_wait() -> None:
    translated = translate_error(
        OpenAIAdsAPIError("slow down", http_status=429, retry_after_seconds=30)
    )

    assert isinstance(translated, RateLimited)
    assert translated.retry_after_seconds == 30
    assert translated.key == "chatgpt:429"


# --- Delivery and money --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "issues", "level", "expected"),
    [
        ("active", [], "campaign", "active"),
        ("paused", [], "campaign", "paused"),
        ("active", ["ad_account_threshold_payment_failed"], "campaign", "billing"),
        ("active", ["review_not_approved", "ad_in_review"], "ad", "rejected"),
        ("active", ["ad_in_review"], "ad", "pending"),
        ("active", ["campaign_budget_exhausted"], "campaign", "finished"),
        ("active", ["campaign_not_active"], "adset", "paused_above"),
        ("active", ["campaign_not_active"], "campaign", "unknown"),
        ("active", ["partial_serving_ad_in_review"], "campaign", "active"),
        ("active", ["campaign_has_no_ad_groups"], "campaign", "unknown"),
    ],
)
def test_delivery_words(
    status: str, issues: list[str], level: Any, expected: str
) -> None:
    assert delivery_of(status=status, issues=issues, level=level) == expected


def test_micros_and_minor_units_round_trip() -> None:
    assert micros_to_minor(5_000_000, "USD") == 500
    assert micros_to_minor(None, "USD") is None
    assert minor_to_micros(500, "USD") == 5_000_000
    assert minor_to_micros(50_000, "UZS") == 500_000_000


# --- Campaigns -----------------------------------------------------------


def test_campaigns_are_listed_without_the_archived() -> None:
    wire = Wire(
        {
            ("GET", "ad_account"): AD_ACCOUNT,
            ("GET", "campaigns"): _page(
                _campaign("c1"), _campaign("c2", status="archived")
            ),
        }
    )

    found = OpenAICampaigns(http=wire.http()).list_campaigns(account=ACCOUNT, token=KEY)

    assert [c.ref.id for c in found] == ["c1"]
    assert found[0].daily_budget_minor == 500
    assert found[0].delivery == "active"
    assert found[0].currency == "USD"


def test_a_campaign_is_found_with_where_it_runs() -> None:
    targeting = {
        "locations": {
            "countries": ["KZ"],
            "include": [
                {"id": "2001959", "canonical_name": "Toshkent (City), Uzbekistan"}
            ],
        }
    }
    wire = Wire(
        {
            ("GET", "campaigns"): _page(
                _campaign("c1"), _campaign("c2", targeting=targeting)
            ),
        }
    )

    with AdsClient(api_key=KEY, http=wire.http()) as client:
        found = campaign_found(client, campaign_id="c2", currency="USD")
        missing = campaign_found(client, campaign_id="c9", currency="USD")

    assert found is not None
    campaign, locations = found
    assert campaign.ref.id == "c2"
    assert locations == Locations(
        countries=("KZ",),
        places=(Place(id="2001959", name="Toshkent (City), Uzbekistan"),),
    )
    assert missing is None


def test_locations_read_back_what_a_launch_writes() -> None:
    sent = campaign_body(_spec(countries=("UZ",), place_ids=("2001959", "2001960")))

    assert locations_of(sent) == Locations(
        countries=("UZ",), places=(Place(id="2001959"), Place(id="2001960"))
    )
    assert locations_of({}) == Locations()
    assert locations_of({"targeting": {"locations": None}}) == Locations()


def test_groups_and_ads_learn_their_parent_from_the_walk() -> None:
    group = {"id": "g1", "name": "G", "status": "active", "bidding_config": {}}
    ad = {
        "id": "a1",
        "name": "A",
        "status": "active",
        "review_status": "in_review",
        "creative": {
            "type": "chat_card",
            "title": "T",
            "body": "B",
            "target_url": "https://gul.uz",
        },
        "serving_issues": [{"code": "ad_in_review"}],
    }
    wire = Wire(
        {
            ("GET", "ad_account"): AD_ACCOUNT,
            ("GET", "campaigns"): _page(_campaign("c1")),
            ("GET", "ad_groups"): _page(group),
            ("GET", "ads"): _page(ad),
        }
    )
    port = OpenAICampaigns(http=wire.http())

    groups = port.list_adsets(account=ACCOUNT, token=KEY)
    ads = port.list_ads(account=ACCOUNT, token=KEY)

    assert groups[0].campaign_ref.id == "c1"
    assert ads[0].adset_ref.id == "g1"
    assert ads[0].delivery == "pending"
    assert ads[0].creative is not None and ads[0].creative.headline == "T"


def test_a_switch_posts_the_verb() -> None:
    wire = Wire({("POST", "campaigns/cmpn_1/pause"): _campaign("cmpn_1", "paused")})

    result = OpenAICampaigns(http=wire.http()).set_status(
        ref=CAMPAIGN, status="paused", token=KEY, dry_run=False
    )

    assert wire.paths() == ["POST campaigns/cmpn_1/pause"]
    assert result.dry_run is False


def test_a_rehearsal_sends_nothing() -> None:
    wire = Wire({})
    port = OpenAICampaigns(http=wire.http(), rehearse_writes=True)

    result = port.set_status(ref=CAMPAIGN, status="active", token=KEY, dry_run=False)
    port.delete(ref=CAMPAIGN, token=KEY, dry_run=False)

    assert wire.seen == []
    assert result.dry_run is True


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(InvalidRequest):
        OpenAICampaigns(http=Wire({}).http()).set_status(
            ref=CAMPAIGN, status="rejected", token=KEY, dry_run=False
        )


def test_a_budget_change_keeps_the_lifetime_limit() -> None:
    current = _campaign(
        "cmpn_1",
        budget={
            "daily_spend_limit_micros": 5_000_000,
            "lifetime_spend_limit_micros": 90_000_000,
        },
    )
    wire = Wire(
        {
            ("GET", "ad_account"): AD_ACCOUNT,
            ("GET", "campaigns/cmpn_1"): current,
            ("POST", "campaigns/cmpn_1"): current,
        }
    )

    OpenAICampaigns(http=wire.http()).set_budget(
        ref=CAMPAIGN, daily_budget_minor=1200, token=KEY, dry_run=False
    )

    assert wire.body("POST", "campaigns/cmpn_1") == {
        "budget": {
            "daily_spend_limit_micros": 12_000_000,
            "lifetime_spend_limit_micros": 90_000_000,
        }
    }


def test_a_budget_lives_on_the_campaign_only() -> None:
    group = ExternalRef(provider="chatgpt", level="adset", id="g1")
    with pytest.raises(InvalidRequest):
        OpenAICampaigns(http=Wire({}).http()).set_budget(
            ref=group, daily_budget_minor=100, token=KEY, dry_run=False
        )


def test_delete_archives() -> None:
    wire = Wire({("POST", "ads/a1/archive"): {"id": "a1"}})
    ad = ExternalRef(provider="chatgpt", level="ad", id="a1")

    OpenAICampaigns(http=wire.http()).delete(ref=ad, token=KEY, dry_run=False)

    assert wire.paths() == ["POST ads/a1/archive"]


# --- Metrics -------------------------------------------------------------


def test_daily_rows_come_from_the_account_report() -> None:
    report = _page(
        {
            "id": "start=1:end=2:entity_id=c1",
            "start_time": 1,
            "end_time": 2,
            "readable_time": "2026-10-30",
            "campaign_id": "c1",
            "impressions": 1200,
            "clicks": 36,
            "spend": 18.42,
        }
    )
    wire = Wire(
        {("GET", "ad_account"): AD_ACCOUNT, ("GET", "ad_account/insights"): report}
    )

    rows = OpenAIMetrics(http=wire.http()).fetch_daily(
        account=ACCOUNT,
        since=date(2026, 10, 30),
        until=date(2026, 10, 31),
        level="campaign",
        token=KEY,
    )

    asked = parse_qs(wire.seen[-1].url.query.decode())
    assert asked["aggregation_level"] == ["campaign"]
    assert asked["time_granularity"] == ["daily"]
    assert json.loads(asked["time_ranges[]"][0]) == {
        "type": "date_range",
        "since": "2026-10-30",
        "until": "2026-10-31",
    }
    assert rows[0].day == date(2026, 10, 30)
    assert (rows[0].spend_minor, rows[0].clicks, rows[0].impressions) == (
        1842,
        36,
        1200,
    )
    assert rows[0].campaign_external_id == "c1"


def test_totals_are_one_row_per_object() -> None:
    report = _page(
        {
            "id": "x",
            "start_time": 1,
            "end_time": 2,
            "ad_group_id": "g1",
            "spend": 3,
            "clicks": 4,
        }
    )
    wire = Wire(
        {("GET", "ad_account"): AD_ACCOUNT, ("GET", "ad_account/insights"): report}
    )

    currency, totals = OpenAIMetrics(http=wire.http()).fetch_totals(
        since=date(2026, 10, 1), until=date(2026, 10, 31), level="adset", token=KEY
    )

    assert currency == "USD"
    assert totals["g1"].spend_minor == 300
    assert parse_qs(wire.seen[-1].url.query.decode())["time_granularity"] == ["none"]


# --- Launch --------------------------------------------------------------


def _spec(**changes: Any) -> ChatCardSpec:
    base: dict[str, Any] = {
        "name": "Gul yetkazib berish",
        "daily_budget_micros": 10_000_000,
        "title": "Toshkentda gul yetkazish",
        "body": "Bir soatda eshigingizgacha. Buyurtma bering.",
        "target_url": "https://gul.uz",
        "countries": ("UZ",),
        "context_hints": ("tug'ilgan kunga gul sovg'a",),
    }
    return ChatCardSpec(**(base | changes))


def _launch_wire() -> Wire:
    routes: dict[tuple[str, str], Any] = {
        ("POST", "upload"): {"file_id": "file_1"},
        ("POST", "campaigns"): _campaign("c1", "paused"),
        ("POST", "ad_groups"): {"id": "g1", "status": "active"},
        ("POST", "ads"): {"id": "a1", "review_status": "in_review"},
        ("POST", "campaigns/c1/activate"): _campaign("c1"),
        ("POST", "campaigns/c1/archive"): _campaign("c1", "archived"),
    }
    return Wire(routes)


def test_a_launch_makes_four_objects_in_order() -> None:
    wire = _launch_wire()
    spec = _spec(image=ImageSpec(content=b"\x89PNG", filename="gul.png"))

    with AdsClient(api_key=KEY, http=wire.http()) as client:
        made = create_chat_campaign(client, spec, key="launch-7")

    assert wire.paths() == [
        "POST upload",
        "POST campaigns",
        "POST ad_groups",
        "POST ads",
        "POST campaigns/c1/activate",
    ]
    assert (made.campaign_id, made.ad_group_id, made.ad_id, made.file_id) == (
        "c1",
        "g1",
        "a1",
        "file_1",
    )
    campaign = wire.body("POST", "campaigns")
    assert campaign["status"] == "paused"
    assert campaign["targeting"] == {"locations": {"countries": ["UZ"]}}
    assert campaign["budget"] == {"daily_spend_limit_micros": 10_000_000}
    group = wire.body("POST", "ad_groups")
    assert group["bidding_config"] == {
        "billing_event_type": "click",
        "strategy": "maximize_clicks",
    }
    assert group["context_hints"] == ["tug'ilgan kunga gul sovg'a"]
    assert wire.body("POST", "ads")["creative"]["file_id"] == "file_1"
    keys = [r.headers.get("Idempotency-Key") for r in wire.seen]
    assert keys[1:4] == ["launch-7:campaign", "launch-7:ad_group", "launch-7:ad"]


def test_a_fixed_bid_goes_with_its_ceiling() -> None:
    wire = _launch_wire()
    with AdsClient(api_key=KEY, http=wire.http()) as client:
        create_chat_campaign(client, _spec(max_bid_micros=2_000_000), key="k")

    assert wire.body("POST", "ad_groups")["bidding_config"] == {
        "billing_event_type": "click",
        "strategy": "fixed_bid",
        "max_bid_micros": 2_000_000,
    }


def test_a_failed_ad_archives_the_campaign() -> None:
    wire = _launch_wire()
    wire.routes[("POST", "ads")] = httpx.Response(
        400, json={"error": {"message": "bad"}}
    )

    with (
        pytest.raises(OpenAIAdsAPIError),
        AdsClient(api_key=KEY, http=wire.http()) as client,
    ):
        create_chat_campaign(client, _spec(), key="k")

    assert wire.paths()[-1] == "POST campaigns/c1/archive"
    assert "POST campaigns/c1/activate" not in wire.paths()


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"title": "ab"}, "title"),
        ({"title": "x" * 51}, "title"),
        ({"body": "x" * 101}, "body"),
        ({"target_url": "gul.uz"}, "target_url"),
        ({"countries": ()}, "locations"),
        ({"countries": ("uz",)}, "countries"),
        ({"daily_budget_micros": 999_999}, "budget"),
    ],
)
def test_a_spec_is_checked_before_any_call(changes: dict[str, Any], field: str) -> None:
    wire = _launch_wire()
    with (
        pytest.raises(InvalidRequest) as caught,
        AdsClient(api_key=KEY, http=wire.http()) as client,
    ):
        create_chat_campaign(client, _spec(**changes), key="k")

    assert caught.value.code == field
    assert wire.seen == []


# --- The bundle ----------------------------------------------------------


def test_the_bundle_speaks_the_ports() -> None:
    found = bundle()

    assert isinstance(found.campaigns, CampaignControlPort)
    assert isinstance(found.metrics, MetricsPort)
    assert isinstance(found.connect, ConnectPort)
    assert _PROVIDER == PROVIDER


def test_the_key_is_used_as_it_was_stored() -> None:
    connect = KeyConnect()

    assert connect.access_token(stored=KEY) == KEY
    with pytest.raises(InvalidRequest):
        connect.authorize_url(redirect_uri="x", state="y")
