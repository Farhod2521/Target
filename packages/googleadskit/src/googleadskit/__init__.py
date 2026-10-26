"""The only place that talks to Google Ads.

Every Google Ads API call goes through here, over REST, so the API version,
the timeouts and the reading of Google's failures have exactly one
implementation.

The package knows nothing about this project. Tokens arrive as plain
strings and configuration through constructors. The stored credential is a
refresh token; :class:`~googleadskit.connect.GoogleConnect` trades it for
an access token through ``googlekit``, Google's one OAuth implementation.
"""

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

# The registry key this package answers to, written once so that
# ``registry.get(PROVIDER)`` and ``ProviderConnection.provider`` cannot drift.
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
