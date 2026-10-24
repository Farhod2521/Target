"""A whole Search campaign, created in one request or not at all."""

from typing import Any, Final, Literal

from adskit.money import ISO_MONEY
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from googleadskit.client import AdsClient

MatchType = Literal["PHRASE", "EXACT"]

HEADLINE_MAX: Final = 30
HEADLINES_MIN: Final = 3
HEADLINES_MAX: Final = 15
DESCRIPTION_MAX: Final = 90
DESCRIPTIONS_MIN: Final = 2
DESCRIPTIONS_MAX: Final = 4
PATH_MAX: Final = 15
KEYWORD_MAX_CHARS: Final = 80
KEYWORD_MAX_WORDS: Final = 10

_MICROS_PLACES: Final = 6


class KeywordSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    match: MatchType = "PHRASE"

    @field_validator("text")
    @classmethod
    def _fits(cls, text: str) -> str:
        text = " ".join(text.split())
        if not text or len(text) > KEYWORD_MAX_CHARS:
            raise ValueError(f"keyword must be 1-{KEYWORD_MAX_CHARS} characters")
        if len(text.split()) > KEYWORD_MAX_WORDS:
            raise ValueError(f"keyword must be at most {KEYWORD_MAX_WORDS} words")
        return text


class SearchCampaignSpec(BaseModel):
    """Everything one Search campaign is made of, checked against Google's limits.

    ``places`` are geo target resource names (``geoTargetConstants/1028523``),
    as :class:`~googleadskit.locations.GoogleAudiences` returns them.
    ``daily_budget_minor`` is in the account's currency, whose code comes
    with it so the micros can be counted. ``phone`` (E.164) adds a call
    asset; Google checks the number against the site.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=255)
    daily_budget_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    final_url: str
    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    path1: str = Field(default="", max_length=PATH_MAX)
    path2: str = Field(default="", max_length=PATH_MAX)
    keywords: tuple[KeywordSpec, ...] = Field(min_length=1)
    negative_keywords: tuple[str, ...] = ()
    places: tuple[str, ...] = Field(min_length=1)
    phone: str = ""
    phone_country: str = ""

    @field_validator("final_url")
    @classmethod
    def _url(cls, url: str) -> str:
        if not url.startswith(("https://", "http://")):
            raise ValueError("final_url must be an http(s) address")
        return url

    @field_validator("headlines")
    @classmethod
    def _headlines(cls, rows: tuple[str, ...]) -> tuple[str, ...]:
        return _texts(rows, low=HEADLINES_MIN, high=HEADLINES_MAX, width=HEADLINE_MAX)

    @field_validator("descriptions")
    @classmethod
    def _descriptions(cls, rows: tuple[str, ...]) -> tuple[str, ...]:
        return _texts(
            rows, low=DESCRIPTIONS_MIN, high=DESCRIPTIONS_MAX, width=DESCRIPTION_MAX
        )

    @model_validator(mode="after")
    def _paths_and_phone(self) -> "SearchCampaignSpec":
        if self.path2 and not self.path1:
            raise ValueError("path2 needs path1")
        if self.phone and not self.phone_country:
            raise ValueError("a phone needs its country")
        return self


class CreatedSearchCampaign(BaseModel):
    """What Google issued, by resource name. Empty after a validation run."""

    model_config = ConfigDict(frozen=True)

    validated_only: bool
    budget: str = ""
    campaign: str = ""
    ad_group: str = ""
    ad: str = ""


def create_search_campaign(
    client: AdsClient,
    customer_id: str,
    spec: SearchCampaignSpec,
    *,
    validate_only: bool = True,
) -> CreatedSearchCampaign:
    """Create ``spec`` in ``customer_id`` atomically, or only validate it."""
    answer = client.post(
        f"customers/{customer_id}/googleAds:mutate",
        {
            "mutateOperations": operations(customer_id, spec),
            "partialFailure": False,
            "validateOnly": validate_only,
        },
    )
    if validate_only:
        return CreatedSearchCampaign(validated_only=True)

    issued = _issued(answer)
    return CreatedSearchCampaign(
        validated_only=False,
        budget=issued.get("campaignBudgetResult", ""),
        campaign=issued.get("campaignResult", ""),
        ad_group=issued.get("adGroupResult", ""),
        ad=issued.get("adGroupAdResult", ""),
    )


def operations(customer_id: str, spec: SearchCampaignSpec) -> list[dict[str, Any]]:
    """The request's operations, parents before children."""
    root = f"customers/{customer_id}"
    budget, campaign, group, asset = (
        f"{root}/campaignBudgets/-1",
        f"{root}/campaigns/-2",
        f"{root}/adGroups/-3",
        f"{root}/assets/-4",
    )
    ops: list[dict[str, Any]] = [
        _create("campaignBudgetOperation", _budget(budget, spec)),
        _create("campaignOperation", _campaign(campaign, budget, spec)),
        _create(
            "adGroupOperation",
            {
                "resourceName": group,
                "campaign": campaign,
                "name": spec.name,
                "type": "SEARCH_STANDARD",
                "status": "ENABLED",
            },
        ),
    ]
    ops += [
        _create(
            "adGroupCriterionOperation",
            {
                "adGroup": group,
                "status": "ENABLED",
                "keyword": {"text": keyword.text, "matchType": keyword.match},
            },
        )
        for keyword in spec.keywords
    ]
    ops.append(_create("adGroupAdOperation", _ad(group, spec)))
    ops += [
        _create(
            "campaignCriterionOperation",
            {"campaign": campaign, "location": {"geoTargetConstant": place}},
        )
        for place in spec.places
    ]
    ops += [
        _create(
            "campaignCriterionOperation",
            {
                "campaign": campaign,
                "negative": True,
                "keyword": {"text": text, "matchType": "PHRASE"},
            },
        )
        for text in spec.negative_keywords
    ]
    if spec.phone:
        ops += _call(asset, campaign, spec)
    return ops


def _create(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    return {kind: {"create": body}}


def _budget(name: str, spec: SearchCampaignSpec) -> dict[str, Any]:
    places = ISO_MONEY.decimal_places(spec.currency)
    return {
        "resourceName": name,
        "name": spec.name,
        "amountMicros": str(spec.daily_budget_minor * 10 ** (_MICROS_PLACES - places)),
        "deliveryMethod": "STANDARD",
        "explicitlyShared": False,
    }


def _campaign(name: str, budget: str, spec: SearchCampaignSpec) -> dict[str, Any]:
    return {
        "resourceName": name,
        "name": spec.name,
        "advertisingChannelType": "SEARCH",
        "status": "ENABLED",
        "campaignBudget": budget,
        "targetSpend": {},
        "networkSettings": {
            "targetGoogleSearch": True,
            "targetSearchNetwork": False,
            "targetContentNetwork": False,
            "targetPartnerSearchNetwork": False,
        },
        "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        "geoTargetTypeSetting": {"positiveGeoTargetType": "PRESENCE"},
    }


def _ad(group: str, spec: SearchCampaignSpec) -> dict[str, Any]:
    search_ad: dict[str, Any] = {
        "headlines": [{"text": text} for text in spec.headlines],
        "descriptions": [{"text": text} for text in spec.descriptions],
    }
    if spec.path1:
        search_ad["path1"] = spec.path1
    if spec.path2:
        search_ad["path2"] = spec.path2
    return {
        "adGroup": group,
        "status": "ENABLED",
        "ad": {"finalUrls": [spec.final_url], "responsiveSearchAd": search_ad},
    }


def _call(asset: str, campaign: str, spec: SearchCampaignSpec) -> list[dict[str, Any]]:
    return [
        _create(
            "assetOperation",
            {
                "resourceName": asset,
                "callAsset": {
                    "countryCode": spec.phone_country.upper(),
                    "phoneNumber": spec.phone,
                },
            },
        ),
        _create(
            "campaignAssetOperation",
            {"campaign": campaign, "asset": asset, "fieldType": "CALL"},
        ),
    ]


def _texts(
    rows: tuple[str, ...], *, low: int, high: int, width: int
) -> tuple[str, ...]:
    cleaned = tuple(" ".join(row.split()) for row in rows)
    if not low <= len(cleaned) <= high:
        raise ValueError(f"needs {low}-{high} texts, got {len(cleaned)}")
    if any(not row or len(row) > width for row in cleaned):
        raise ValueError(f"every text must be 1-{width} characters")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("texts must not repeat")
    return cleaned


def _issued(answer: dict[str, Any]) -> dict[str, str]:
    """The first resource name of each kind Google answered with."""
    issued: dict[str, str] = {}
    for row in answer.get("mutateOperationResponses") or []:
        for kind, result in row.items():
            if isinstance(result, dict) and kind not in issued:
                issued[kind] = str(result.get("resourceName") or "")
    return issued


__all__ = [
    "CreatedSearchCampaign",
    "KeywordSpec",
    "MatchType",
    "SearchCampaignSpec",
    "create_search_campaign",
    "operations",
]
