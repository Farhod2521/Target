"""ChatGPT Ads as a provider bundle for ``adskit.registry``.

Connect, campaigns and metrics are real. The rest stand in with
:class:`adskit.Unavailable`, which refuses by name at the call site.
"""

from adskit import Unavailable
from adskit.registry import ProviderBundle

from openaiadskit.campaigns import OpenAICampaigns
from openaiadskit.connect import KeyConnect
from openaiadskit.metrics import OpenAIMetrics

# Spelled once more on purpose, and pinned to the root's by a test.
_PROVIDER = "chatgpt"


def bundle(*, rehearse_writes: bool = True) -> ProviderBundle:
    """Everything ChatGPT Ads can do today, in one object for the registry.

    ``rehearse_writes`` sends no write at all whatever the caller asked -
    OpenAI has no validate-only switch on single objects.
    """
    return ProviderBundle(
        campaigns=OpenAICampaigns(rehearse_writes=rehearse_writes),
        metrics=OpenAIMetrics(),
        leads=Unavailable(provider=_PROVIDER, port="leads"),
        audiences=Unavailable(provider=_PROVIDER, port="audiences"),
        audience_sources=Unavailable(provider=_PROVIDER, port="audience sources"),
        conversions=Unavailable(provider=_PROVIDER, port="conversions"),
        connect=KeyConnect(),
    )


__all__ = ["bundle"]
