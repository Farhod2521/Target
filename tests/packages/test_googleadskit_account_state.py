"""googleadskit: the account's state, end dates and a campaign's places."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from adskit.errors import InvalidRequest
from adskit.refs import ExternalRef
from googleadskit.campaigns import GoogleCampaigns
from googleadskit.locations import GoogleAudiences

CAMPAIGN = "customers/111/campaigns/5"
ACCOUNT = ExternalRef(provider="google", level="account", id="111")
REF = ExternalRef(provider="google", level="campaign", id=CAMPAIGN)
TASHKENT, SAMARKAND, BUKHARA = (
    "geoTargetConstants/1",
    "geoTargetConstants/2",
    "geoTargetConstants/3",
)

Handler = Callable[[httpx.Request], httpx.Response]


def _http(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _results(*rows: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"results": list(rows)})


def _account(billing: httpx.Response, **customer: Any) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if "FROM billing_setup" in json.loads(request.content)["query"]:
            return billing
        return _results({"customer": {"status": "ENABLED"} | customer})

    return GoogleCampaigns(http=_http(handler)).read_account(account=ACCOUNT, token="t")


def test_an_approved_billing_setup_can_pay() -> None:
    state = _account(_results({"billingSetup": {"status": "APPROVED"}}))

    assert state.standing == "active"
    assert state.has_payment_method is True


@pytest.mark.parametrize(
    "billing", [_results(), _results({"billingSetup": {"status": "PENDING"}})]
)
def test_no_approved_billing_setup_cannot_pay(billing: httpx.Response) -> None:
    assert _account(billing).has_payment_method is False


def test_billing_closed_to_this_access_level_is_not_knowing() -> None:
    refused = httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}})

    assert _account(refused).has_payment_method is None


def test_a_test_account_needs_no_billing() -> None:
    state = _account(_results(), testAccount=True)

    assert state.has_payment_method is None


def test_a_cancelled_account_is_closed() -> None:
    state = _account(_results(), status="CANCELED")

    assert state.standing == "closed"


def test_groups_are_counted_inside_one_campaign() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        assert f"campaign.resource_name = '{CAMPAIGN}'" in query
        assert "ad_group.status != 'REMOVED'" in query
        return _results({"adGroup": {"id": "1"}}, {"adGroup": {"id": "2"}})

    port = GoogleCampaigns(http=_http(handler))

    assert port.count_adsets(campaign=REF, token="t") == 2


def test_an_end_date_is_the_last_second_of_that_day() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("customers/111/campaigns:mutate")
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    GoogleCampaigns(http=_http(handler)).set_end_time(
        ref=REF, end_time="2026-12-31T23:59:59+05:00", token="t", dry_run=False
    )

    assert sent[0]["validateOnly"] is False
    assert sent[0]["operations"] == [
        {
            "update": {
                "resourceName": CAMPAIGN,
                "endDateTime": "2026-12-31 23:59:59",
            },
            "updateMask": "endDateTime",
        }
    ]


def test_a_group_has_no_end_date_on_google() -> None:
    group = ExternalRef(provider="google", level="adset", id="customers/111/adGroups/1")
    port = GoogleCampaigns(http=_http(lambda _r: httpx.Response(200, json={})))

    with pytest.raises(InvalidRequest):
        port.set_end_time(ref=group, end_time="2026-12-31", token="t", dry_run=False)


def _held(*places: str) -> list[dict[str, Any]]:
    return [
        {
            "campaignCriterion": {
                "resourceName": f"customers/111/campaignCriteria/5~{place[-1]}",
                "location": {"geoTargetConstant": place},
            }
        }
        for place in places
    ]


def _places(*held: str) -> tuple[GoogleAudiences, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("googleAds:search"):
            query = json.loads(request.content)["query"]
            if "FROM geo_target_constant" in query:
                return _results(
                    {
                        "geoTargetConstant": {
                            "resourceName": TASHKENT,
                            "name": "Tashkent",
                        }
                    }
                )
            assert "campaign_criterion.negative = false" in query
            return _results(*_held(*held))
        assert request.url.path.endswith("customers/111/campaignCriteria:mutate")
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    return GoogleAudiences(http=_http(handler)), sent


def test_only_the_difference_in_places_is_sent() -> None:
    port, sent = _places(TASHKENT, SAMARKAND)

    port.apply(
        ref=REF, targeting={"places": [TASHKENT, BUKHARA]}, token="t", dry_run=False
    )

    assert sent[0]["operations"] == [
        {"remove": "customers/111/campaignCriteria/5~2"},
        {"create": {"campaign": CAMPAIGN, "location": {"geoTargetConstant": BUKHARA}}},
    ]


def test_the_same_places_send_nothing() -> None:
    port, sent = _places(TASHKENT)

    port.apply(ref=REF, targeting={"places": [TASHKENT]}, token="t", dry_run=False)

    assert sent == []


def test_a_campaign_is_never_left_without_places() -> None:
    port, _sent = _places(TASHKENT)

    with pytest.raises(InvalidRequest):
        port.apply(ref=REF, targeting={"places": []}, token="t", dry_run=False)


def test_a_rehearsal_changes_no_places() -> None:
    held = _held(TASHKENT)
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("googleAds:search"):
            return _results(*held)
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    port = GoogleAudiences(http=_http(handler), rehearse_writes=True)

    result = port.apply(
        ref=REF, targeting={"places": [BUKHARA]}, token="t", dry_run=False
    )

    assert result.dry_run is True
    assert sent[0]["validateOnly"] is True


def test_places_are_read_with_their_names_and_compared_as_a_set() -> None:
    port, _sent = _places(TASHKENT)

    held = port.read_targeting(ref=REF, token="t")

    assert held == {"places": [TASHKENT], "names": {TASHKENT: "Tashkent"}}
    assert port.same_targeting(
        {"places": [TASHKENT, BUKHARA]}, {"places": [BUKHARA, TASHKENT]}
    )
    assert not port.same_targeting({"places": [TASHKENT]}, {"places": [BUKHARA]})
