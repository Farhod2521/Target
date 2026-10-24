"""googleadskit: one Search campaign in one request, places, keyword figures."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from adskit import AudiencePort, PortNotAvailable
from adskit.errors import InvalidRequest
from googleadskit import (
    AdsClient,
    KeywordSpec,
    SearchCampaignSpec,
    create_search_campaign,
    keyword_ideas,
    keyword_volumes,
)
from googleadskit.adapter import bundle
from googleadskit.launch import operations
from googleadskit.locations import GoogleAudiences
from pydantic import ValidationError

Handler = Callable[[httpx.Request], httpx.Response]
CUSTOMER = "1234567890"
FAILURE_TYPE = "type.googleapis.com/google.ads.googleads.v25.errors.GoogleAdsFailure"


def _http(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _recording(answer: dict[str, Any]) -> tuple[Handler, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=answer)

    return handler, sent


def _spec(**fields: Any) -> SearchCampaignSpec:
    values: dict[str, Any] = {
        "name": "Gullar - qidiruv",
        "daily_budget_minor": 500,
        "currency": "USD",
        "final_url": "https://gul.uz",
        "headlines": ("Gullar yetkazib berish", "Toshkentda gullar", "Bugun buyurtma"),
        "descriptions": (
            "Yangi gullar uyingizgacha.",
            "Buyurtma bering, bir soatda yetkazamiz.",
        ),
        "keywords": (KeywordSpec(text="gul yetkazib berish"),),
        "places": ("geoTargetConstants/1028523",),
    }
    return SearchCampaignSpec(**(values | fields))


# --- The spec -----------------------------------------------------------


def test_a_headline_over_thirty_characters_is_refused() -> None:
    with pytest.raises(ValidationError):
        _spec(headlines=("x" * 31, "b", "c"))


def test_too_few_headlines_or_descriptions_are_refused() -> None:
    with pytest.raises(ValidationError):
        _spec(headlines=("a", "b"))
    with pytest.raises(ValidationError):
        _spec(descriptions=("only one",))


def test_repeated_headlines_are_refused() -> None:
    with pytest.raises(ValidationError):
        _spec(headlines=("a", "a", "b"))


def test_a_spec_needs_a_website_and_a_place() -> None:
    with pytest.raises(ValidationError):
        _spec(final_url="gul.uz")
    with pytest.raises(ValidationError):
        _spec(places=())


def test_a_keyword_over_ten_words_is_refused() -> None:
    with pytest.raises(ValidationError):
        KeywordSpec(text=" ".join(["so'z"] * 11))


# --- The request --------------------------------------------------------


def test_the_operations_build_the_whole_campaign_parents_first() -> None:
    ops = operations(CUSTOMER, _spec(negative_keywords=("bepul",)))
    kinds = [next(iter(op)) for op in ops]

    assert kinds[:3] == [
        "campaignBudgetOperation",
        "campaignOperation",
        "adGroupOperation",
    ]
    budget = ops[0]["campaignBudgetOperation"]["create"]
    assert budget["amountMicros"] == "5000000"
    assert budget["explicitlyShared"] is False
    campaign = ops[1]["campaignOperation"]["create"]
    assert campaign["targetSpend"] == {}
    assert campaign["networkSettings"]["targetContentNetwork"] is False
    # People in the places, not people elsewhere searching about them.
    assert campaign["geoTargetTypeSetting"] == {"positiveGeoTargetType": "PRESENCE"}
    assert (
        campaign["containsEuPoliticalAdvertising"]
        == "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
    )
    assert "adGroupAdOperation" in kinds
    criteria = [
        op["campaignCriterionOperation"]["create"]
        for op in ops
        if "campaignCriterionOperation" in op
    ]
    assert {"geoTargetConstant": "geoTargetConstants/1028523"} in [
        row.get("location") for row in criteria
    ]
    assert any(row.get("negative") for row in criteria)
    # No language criterion: Uzbek is not a Google language.
    assert not any("language" in row for row in criteria)


def test_a_phone_adds_a_call_asset_linked_to_the_campaign() -> None:
    ops = operations(CUSTOMER, _spec(phone="+998901234567", phone_country="uz"))

    asset = next(op["assetOperation"]["create"] for op in ops if "assetOperation" in op)
    link = next(
        op["campaignAssetOperation"]["create"]
        for op in ops
        if "campaignAssetOperation" in op
    )
    assert asset["callAsset"] == {"countryCode": "UZ", "phoneNumber": "+998901234567"}
    assert link["fieldType"] == "CALL"
    assert link["asset"] == asset["resourceName"]


def test_validation_only_sends_validate_only_and_returns_no_names() -> None:
    handler, sent = _recording({})
    with AdsClient(token="tok", http=_http(handler)) as client:
        created = create_search_campaign(client, CUSTOMER, _spec())

    body = json.loads(sent[0].content)
    assert sent[0].url.path.endswith(f"customers/{CUSTOMER}/googleAds:mutate")
    assert body["validateOnly"] is True
    assert body["partialFailure"] is False
    assert created.validated_only
    assert created.campaign == ""


def test_a_real_create_reads_back_what_google_issued() -> None:
    handler, _sent = _recording(
        {
            "mutateOperationResponses": [
                {
                    "campaignBudgetResult": {
                        "resourceName": "customers/C/campaignBudgets/1"
                    }
                },
                {"campaignResult": {"resourceName": "customers/C/campaigns/2"}},
                {"adGroupResult": {"resourceName": "customers/C/adGroups/3"}},
                {"adGroupCriterionResult": {"resourceName": "customers/C/x/4"}},
                {"adGroupAdResult": {"resourceName": "customers/C/adGroupAds/3~5"}},
            ]
        }
    )
    with AdsClient(token="tok", http=_http(handler)) as client:
        created = create_search_campaign(client, CUSTOMER, _spec(), validate_only=False)

    assert not created.validated_only
    assert created.campaign == "customers/C/campaigns/2"
    assert created.ad == "customers/C/adGroupAds/3~5"


# --- Places -------------------------------------------------------------


def test_places_are_suggested_with_their_context() -> None:
    handler, sent = _recording(
        {
            "geoTargetConstantSuggestions": [
                {
                    "geoTargetConstant": {
                        "resourceName": "geoTargetConstants/1028523",
                        "name": "Tashkent",
                        "countryCode": "UZ",
                        "targetType": "City",
                        "status": "ENABLED",
                        "canonicalName": "Tashkent,Tashkent,Uzbekistan",
                    }
                },
                {
                    "geoTargetConstant": {
                        "resourceName": "geoTargetConstants/9",
                        "name": "Old",
                        "targetType": "City",
                        "status": "REMOVAL_PLANNED",
                    }
                },
            ]
        }
    )

    found = GoogleAudiences(http=_http(handler)).find_locations(
        query="Toshkent", country_code="uz", token="tok"
    )

    assert len(found) == 1
    place = found[0]
    assert place.ref.id == "geoTargetConstants/1028523"
    assert (place.kind, place.context, place.supports_radius) == (
        "city",
        "Tashkent, Uzbekistan",
        True,
    )
    body = json.loads(sent[0].content)
    assert body["countryCode"] == "UZ"
    assert body["locationNames"] == {"names": ["Toshkent"]}


def test_the_bundle_answers_places_and_refuses_metas_audience_half() -> None:
    audiences = bundle().audiences

    assert isinstance(audiences, AudiencePort)
    with pytest.raises(PortNotAvailable):
        audiences.find_interests(names=["gul"], token="tok")


# --- Keyword figures ----------------------------------------------------


def test_volumes_are_read_for_exactly_the_keywords_given() -> None:
    handler, sent = _recording(
        {
            "results": [
                {
                    "text": "gul yetkazib berish",
                    "keywordMetrics": {
                        "avgMonthlySearches": "1300",
                        "competition": "MEDIUM",
                    },
                }
            ]
        }
    )
    with AdsClient(token="tok", http=_http(handler)) as client:
        found = keyword_volumes(
            client,
            CUSTOMER,
            keywords=["gul yetkazib berish"],
            places=["geoTargetConstants/2860"],
        )

    assert found[0].monthly_searches == 1300
    assert found[0].competition == "medium"
    body = json.loads(sent[0].content)
    assert sent[0].url.path.endswith(":generateKeywordHistoricalMetrics")
    # No language: every language is counted.
    assert "language" not in body


def test_ideas_come_back_most_searched_first() -> None:
    handler, _sent = _recording(
        {
            "results": [
                {"text": "a", "keywordIdeaMetrics": {"avgMonthlySearches": "10"}},
                {"text": "b", "keywordIdeaMetrics": {"avgMonthlySearches": "90"}},
                {"text": "c", "keywordIdeaMetrics": {}},
            ]
        }
    )
    with AdsClient(token="tok", http=_http(handler)) as client:
        ideas = keyword_ideas(client, CUSTOMER, seeds=["gul"], places=[])

    assert [idea.text for idea in ideas] == ["b", "a", "c"]


def test_no_keywords_means_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("nothing should be sent")

    with AdsClient(token="tok", http=_http(handler)) as client:
        assert keyword_volumes(client, CUSTOMER, keywords=[], places=[]) == []


def test_a_refused_create_is_a_google_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "bad",
                    "details": [
                        {
                            "@type": FAILURE_TYPE,
                            "errors": [
                                {
                                    "errorCode": {
                                        "campaignError": "DUPLICATE_CAMPAIGN_NAME"
                                    }
                                }
                            ],
                        }
                    ],
                }
            },
        )

    from googleadskit import GoogleAdsAPIError, translate_error

    with (
        AdsClient(token="tok", http=_http(handler)) as client,
        pytest.raises(GoogleAdsAPIError) as caught,
    ):
        create_search_campaign(client, CUSTOMER, _spec(), validate_only=False)

    translated = translate_error(caught.value)
    assert isinstance(translated, InvalidRequest)
    assert translated.code == "DUPLICATE_CAMPAIGN_NAME"
