"""The only place that talks to Google Ads."""

from typing import Final

from adskit.refs import ProviderName

from googleadskit.accounts import describe_customer, list_accounts, list_customer_ids
from googleadskit.client import API_VERSION, AdsClient
from googleadskit.dto import CustomerDTO
from googleadskit.errors import (
    GoogleAdsAPIError,
    GoogleAdsError,
    GoogleAdsOutcomeUnknown,
    GoogleAdsUnreachable,
)
from googleadskit.keywords import KeywordVolumeDTO, keyword_ideas, keyword_volumes
from googleadskit.launch import (
    CreatedSearchCampaign,
    KeywordSpec,
    SearchCampaignSpec,
    create_search_campaign,
)
from googleadskit.locations import country_target
from googleadskit.rows import BUDGET_CONSTRAINED
from googleadskit.translate import translate_error

PROVIDER: Final = ProviderName("google")

__all__ = [
    "API_VERSION",
    "BUDGET_CONSTRAINED",
    "PROVIDER",
    "AdsClient",
    "CreatedSearchCampaign",
    "CustomerDTO",
    "GoogleAdsAPIError",
    "GoogleAdsError",
    "GoogleAdsOutcomeUnknown",
    "GoogleAdsUnreachable",
    "KeywordSpec",
    "KeywordVolumeDTO",
    "SearchCampaignSpec",
    "country_target",
    "create_search_campaign",
    "describe_customer",
    "keyword_ideas",
    "keyword_volumes",
    "list_accounts",
    "list_customer_ids",
    "translate_error",
]
