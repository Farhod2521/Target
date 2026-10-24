"""Google Ads as a provider bundle for ``adskit.registry``."""

from adskit import Unavailable
from adskit.registry import ProviderBundle

from googleadskit.campaigns import GoogleCampaigns
from googleadskit.connect import GoogleConnect
from googleadskit.locations import GoogleAudiences
from googleadskit.metrics import GoogleMetrics

_PROVIDER = "google"


def bundle(
    *, client_id: str = "", client_secret: str = "", rehearse_writes: bool = True
) -> ProviderBundle:
    """Everything Google can do today, in one object for the registry."""
    return ProviderBundle(
        campaigns=GoogleCampaigns(rehearse_writes=rehearse_writes),
        metrics=GoogleMetrics(),
        leads=Unavailable(provider=_PROVIDER, port="leads"),
        audiences=GoogleAudiences(),
        audience_sources=Unavailable(provider=_PROVIDER, port="audience sources"),
        conversions=Unavailable(provider=_PROVIDER, port="conversions"),
        connect=GoogleConnect(client_id=client_id, client_secret=client_secret),
    )


__all__ = ["bundle"]
