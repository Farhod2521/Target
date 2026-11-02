"""The only place that talks to ChatGPT Ads (OpenAI's Advertiser API).

Every call goes through here, over REST, so the base URL, the timeouts and
the reading of OpenAI's failures have exactly one implementation.

The package knows nothing about this project. The credential is the
advertiser's own API key, scoped by OpenAI to one ad account, and arrives
as a plain string.
"""

from typing import Final

from adskit.refs import ProviderName

from openaiadskit.accounts import (
    AdAccountInfo,
    PlaceInfo,
    read_ad_account,
    search_places,
)
from openaiadskit.client import API_VERSION, AdsClient
from openaiadskit.errors import (
    OpenAIAdsAPIError,
    OpenAIAdsError,
    OpenAIAdsOutcomeUnknown,
    OpenAIAdsUnreachable,
)
from openaiadskit.launch import (
    ChatCardSpec,
    CreatedChatCampaign,
    ImageSpec,
    create_chat_campaign,
)
from openaiadskit.translate import translate_error

# The registry key this package answers to, written once so that
# ``registry.get(PROVIDER)`` and ``ProviderConnection.provider`` cannot drift.
PROVIDER: Final = ProviderName("chatgpt")

__all__ = [
    "API_VERSION",
    "PROVIDER",
    "AdAccountInfo",
    "AdsClient",
    "ChatCardSpec",
    "CreatedChatCampaign",
    "ImageSpec",
    "OpenAIAdsAPIError",
    "OpenAIAdsError",
    "OpenAIAdsOutcomeUnknown",
    "OpenAIAdsUnreachable",
    "PlaceInfo",
    "create_chat_campaign",
    "read_ad_account",
    "search_places",
    "translate_error",
]
