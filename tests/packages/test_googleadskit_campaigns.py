"""googleadskit: campaigns, ad groups, ads, their status, and daily figures."""

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from adskit import CampaignControlPort, MetricsPort
from adskit.errors import AuthFailed, InvalidRequest
from adskit.refs import ExternalRef
from googleadskit.adapter import bundle
from googleadskit.campaigns import GoogleCampaigns, delivery_of, micros_to_minor
from googleadskit.metrics import GoogleMetrics
from googleadskit.resources import customer_of, resource_name

Handler = Callable[[httpx.Request], httpx.Response]

CUSTOMER = "1234567890"
ACCOUNT = ExternalRef(provider="google", level="account", id=CUSTOMER)
CAMPAIGN = f"customers/{CUSTOMER}/campaigns/11"
GROUP = f"customers/{CUSTOMER}/adGroups/22"
AD = f"customers/{CUSTOMER}/adGroupAds/22~33"
BUDGET = f"customers/{CUSTOMER}/campaignBudgets/44"


def _http(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _answer(*rows: dict[str, Any]) -> Handler:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": list(rows)})

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def _query(request: httpx.Request) -> str:
    return str(json.loads(request.content)["query"])


# --- Names and words ----------------------------------------------------


def test_resource_names_carry_the_customer() -> None:
    name = resource_name(CUSTOMER, "adset", "22")

    assert name == GROUP
    assert customer_of(name) == CUSTOMER


def test_a_bare_id_is_not_a_resource_name() -> None:
    with pytest.raises(InvalidRequest):
        customer_of("11")


@pytest.mark.parametrize(
    ("status", "primary", "expected"),
    [
        ("ENABLED", "ELIGIBLE", "active"),
        ("ENABLED", "LIMITED", "active"),
        ("PAUSED", "PAUSED", "paused"),
        ("ENABLED", "PAUSED", "paused_above"),
        ("ENABLED", "ENDED", "finished"),
        ("ENABLED", "PENDING", "pending"),
        ("ENABLED", "NOT_ELIGIBLE", "rejected"),
        ("ENABLED", "SOMETHING_NEW", "unknown"),
    ],
)
def test_delivery_words(status: str, primary: str, expected: str) -> None:
    assert delivery_of(status=status, primary_status=primary) == expected


def test_micros_become_cents_and_whole_yen() -> None:
    assert micros_to_minor("12345678", "USD") == 1235
    assert micros_to_minor("1000000000", "JPY") == 1000
    assert micros_to_minor(None, "USD") is None


def test_the_bundle_now_answers_campaigns_and_metrics() -> None:
    google = bundle()

    assert isinstance(google.campaigns, CampaignControlPort)
    assert isinstance(google.metrics, MetricsPort)


# --- Listing ------------------------------------------------------------


def test_campaigns_are_listed_with_budget_and_delivery() -> None:
    handler = _answer(
        {
            "campaign": {
                "resourceName": CAMPAIGN,
                "name": "Qidiruv",
                "status": "ENABLED",
                "primaryStatus": "ELIGIBLE",
                "advertisingChannelType": "SEARCH",
            },
            "campaignBudget": {"amountMicros": "5000000"},
            "customer": {"currencyCode": "USD"},
        }
    )

    found = GoogleCampaigns(http=_http(handler)).list_campaigns(
        account=ACCOUNT, token="tok"
    )

    assert len(found) == 1
    campaign = found[0]
    assert campaign.ref.id == CAMPAIGN
    assert campaign.delivery == "active"
    assert campaign.daily_budget_minor == 500
    assert campaign.objective_raw == "SEARCH"
    request = handler.seen[0]  # type: ignore[attr-defined]
    assert request.url.path.endswith(f"customers/{CUSTOMER}/googleAds:search")
    assert "status != 'REMOVED'" in _query(request)


def test_groups_and_ads_point_at_their_parents() -> None:
    groups = GoogleCampaigns(
        http=_http(
            _answer(
                {
                    "adGroup": {
                        "resourceName": GROUP,
                        "name": "Guruh",
                        "status": "ENABLED",
                        "primaryStatus": "PAUSED",
                    },
                    "campaign": {"resourceName": CAMPAIGN},
                }
            )
        )
    ).list_adsets(account=ACCOUNT, token="tok")
    ads = GoogleCampaigns(
        http=_http(
            _answer(
                {
                    "adGroupAd": {
                        "resourceName": AD,
                        "status": "ENABLED",
                        "primaryStatus": "ELIGIBLE",
                        "ad": {"type": "RESPONSIVE_SEARCH_AD"},
                    },
                    "adGroup": {"resourceName": GROUP},
                }
            )
        )
    ).list_ads(account=ACCOUNT, token="tok")

    assert groups[0].campaign_ref.id == CAMPAIGN
    assert groups[0].delivery == "paused_above"
    assert ads[0].adset_ref.id == GROUP
    assert ads[0].name == "RESPONSIVE_SEARCH_AD"


def test_a_refused_token_reads_as_auth_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"status": "UNAUTHENTICATED", "message": "no"}}
        )

    with pytest.raises(AuthFailed):
        GoogleCampaigns(http=_http(handler)).list_campaigns(
            account=ACCOUNT, token="tok"
        )


# --- Status -------------------------------------------------------------


def test_status_is_read_by_resource_name() -> None:
    handler = _answer(
        {
            "campaign": {
                "resourceName": CAMPAIGN,
                "status": "PAUSED",
                "primaryStatus": "PAUSED",
            },
            "campaignBudget": {"amountMicros": "2000000"},
            "customer": {"currencyCode": "USD"},
        }
    )
    ref = ExternalRef(provider="google", level="campaign", id=CAMPAIGN)

    status = GoogleCampaigns(http=_http(handler)).get_status(ref=ref, token="tok")

    assert status.delivery == "paused"
    assert status.daily_budget_minor == 200
    assert f"campaign.resource_name = '{CAMPAIGN}'" in _query(
        handler.seen[0]  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_pausing_mutates_by_name_and_dry_run_only_validates(dry_run: bool) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": [{"resourceName": AD}]})

    ref = ExternalRef(provider="google", level="ad", id=AD)
    result = GoogleCampaigns(http=_http(handler)).set_status(
        ref=ref, status="paused", token="tok", dry_run=dry_run
    )

    body = json.loads(sent[0].content)
    assert sent[0].url.path.endswith(f"customers/{CUSTOMER}/adGroupAds:mutate")
    assert body["operations"][0]["update"] == {"resourceName": AD, "status": "PAUSED"}
    assert body["validateOnly"] is dry_run
    assert result.applied == {"status": "paused"}
    assert result.dry_run is dry_run


def test_a_state_nobody_can_ask_for_is_refused_before_sending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be sent")

    ref = ExternalRef(provider="google", level="campaign", id=CAMPAIGN)
    with pytest.raises(InvalidRequest):
        GoogleCampaigns(http=_http(handler)).set_status(
            ref=ref, status="rejected", token="tok"
        )


def test_a_shared_budget_and_a_budget_held_campaign_are_said() -> None:
    handler = _answer(
        {
            "campaign": {
                "resourceName": CAMPAIGN,
                "status": "ENABLED",
                "primaryStatus": "LIMITED",
                "primaryStatusReasons": ["BUDGET_CONSTRAINED"],
            },
            "campaignBudget": {
                "resourceName": BUDGET,
                "amountMicros": "5000000",
                "explicitlyShared": True,
            },
            "customer": {"currencyCode": "USD"},
        }
    )

    campaign = GoogleCampaigns(http=_http(handler)).list_campaigns(
        account=ACCOUNT, token="tok"
    )[0]

    assert campaign.shared_budget_id == BUDGET
    assert [row.code for row in campaign.recommendations] == ["BUDGET_CONSTRAINED"]


def test_an_own_budget_is_not_called_shared() -> None:
    handler = _answer(
        {
            "campaign": {"resourceName": CAMPAIGN, "status": "ENABLED"},
            "campaignBudget": {"resourceName": BUDGET, "explicitlyShared": False},
            "customer": {"currencyCode": "USD"},
        }
    )

    campaign = GoogleCampaigns(http=_http(handler)).list_campaigns(
        account=ACCOUNT, token="tok"
    )[0]

    assert campaign.shared_budget_id == ""
    assert campaign.recommendations == ()


@pytest.mark.parametrize("dry_run", [True, False])
def test_the_budget_changes_where_it_is(dry_run: bool) -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path.endswith("googleAds:search"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "campaignBudget": {"resourceName": BUDGET},
                            "customer": {"currencyCode": "USD"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    ref = ExternalRef(provider="google", level="campaign", id=CAMPAIGN)
    result = GoogleCampaigns(http=_http(handler)).set_budget(
        ref=ref, daily_budget_minor=750, token="tok", dry_run=dry_run
    )

    assert f"campaign.resource_name = '{CAMPAIGN}'" in _query(sent[0])
    body = json.loads(sent[1].content)
    assert sent[1].url.path.endswith(f"customers/{CUSTOMER}/campaignBudgets:mutate")
    # The amount on the budget the campaign has - never a new budget.
    assert body["operations"][0] == {
        "update": {"resourceName": BUDGET, "amountMicros": "7500000"},
        "updateMask": "amountMicros",
    }
    assert body["validateOnly"] is dry_run
    assert result.applied == {"daily_budget_minor": 750}
    assert result.dry_run is dry_run


def test_a_group_has_no_budget_to_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be sent")

    ref = ExternalRef(provider="google", level="adset", id=GROUP)
    with pytest.raises(InvalidRequest):
        GoogleCampaigns(http=_http(handler)).set_budget(
            ref=ref, daily_budget_minor=500, token="tok"
        )


def test_removing_sends_the_name_and_a_rehearsal_only_validates() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    ref = ExternalRef(provider="google", level="campaign", id=CAMPAIGN)
    result = GoogleCampaigns(http=_http(handler), rehearse_writes=True).delete(
        ref=ref, token="tok", dry_run=False
    )

    body = json.loads(sent[0].content)
    assert sent[0].url.path.endswith(f"customers/{CUSTOMER}/campaigns:mutate")
    assert body == {"operations": [{"remove": CAMPAIGN}], "validateOnly": True}
    assert result.dry_run is True


# --- Figures ------------------------------------------------------------


def test_daily_figures_in_minor_units_and_percent() -> None:
    handler = _answer(
        {
            "adGroup": {"resourceName": GROUP, "name": "Guruh"},
            "campaign": {"resourceName": CAMPAIGN},
            "segments": {"date": "2026-10-01"},
            "metrics": {
                "costMicros": "2500000",
                "impressions": "1000",
                "clicks": "50",
                "conversions": 3.6,
                "ctr": 0.05,
                "averageCpm": "2500000",
                "averageCpc": "50000",
            },
            "customer": {"currencyCode": "USD"},
        }
    )

    rows = GoogleMetrics(http=_http(handler)).fetch_daily(
        account=ACCOUNT,
        since=date(2026, 9, 1),
        until=date(2026, 10, 1),
        level="adset",
        token="tok",
    )

    row = rows[0]
    assert row.ref.id == GROUP
    assert row.day == date(2026, 10, 1)
    assert (row.campaign_external_id, row.adset_external_id) == (CAMPAIGN, GROUP)
    assert row.spend_minor == 250
    assert (row.impressions, row.clicks) == (1000, 50)
    # Google's conversions are a result, never leads.
    assert (row.results_reported, row.leads_reported) == (4, 0)
    assert row.ctr == Decimal("5.00")
    assert (row.cpm_minor, row.cpc_minor) == (250, 5)
    assert row.object_name == "Guruh"
    query = _query(handler.seen[0])  # type: ignore[attr-defined]
    assert "BETWEEN '2026-09-01' AND '2026-10-01'" in query
    # Removed objects keep their figures.
    assert "REMOVED" not in query


def test_breakdowns_are_not_cut_yet() -> None:
    assert (
        GoogleMetrics().fetch_breakdown(
            account=ACCOUNT,
            since=date(2026, 9, 1),
            until=date(2026, 10, 1),
            level="adset",
            kind="region",  # type: ignore[arg-type]
            token="tok",
        )
        == []
    )


def test_a_rehearsing_deployment_never_writes_live() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    ref = ExternalRef(provider="google", level="campaign", id=CAMPAIGN)
    result = GoogleCampaigns(http=_http(handler), rehearse_writes=True).set_status(
        ref=ref, status="paused", token="tok", dry_run=False
    )

    assert json.loads(sent[0].content)["validateOnly"] is True
    assert result.dry_run is True


def test_objects_are_read_by_name_one_search_per_level_asked() -> None:
    """The narrow read a launch waits on: its own names, nothing else, and
    no search at all for a level it did not name."""
    handler = _answer(
        {
            "campaign": {
                "resourceName": CAMPAIGN,
                "name": "Qidiruv",
                "status": "PAUSED",
                "primaryStatus": "PAUSED",
                "advertisingChannelType": "SEARCH",
            },
            "campaignBudget": {"amountMicros": "5000000"},
            "customer": {"currencyCode": "USD"},
        }
    )

    found = GoogleCampaigns(http=_http(handler)).read_objects(
        account=ACCOUNT,
        refs=[ExternalRef(provider="google", level="campaign", id=CAMPAIGN)],
        token="tok",
    )

    assert [c.ref.id for c in found.campaigns] == [CAMPAIGN]
    assert found.adsets == ()
    assert found.ads == ()
    seen = handler.seen  # type: ignore[attr-defined]
    assert len(seen) == 1
    assert f"campaign.resource_name IN ('{CAMPAIGN}')" in _query(seen[0])
