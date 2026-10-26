"""Google Ads as a provider bundle for ``adskit.registry``.

Connect, campaigns, metrics and places are real. The rest stand in with
:class:`adskit.Unavailable`, which refuses by name at the call site: a
screen that reaches for Google's leads before they are built fails saying
"leads", not somewhere unrelated. Each one is replaced as the part of the
work that needs it is written.
"""

from adskit import Unavailable
from adskit.registry import ProviderBundle

from googleadskit.campaigns import GoogleCampaigns
from googleadskit.connect import GoogleConnect
from googleadskit.locations import GoogleAudiences
from googleadskit.metrics import GoogleMetrics

# Written here rather than imported from the package root, which imports
# this module's neighbours: the registry key, spelled once more on purpose
# and pinned to the root's by a test.
_PROVIDER = "google"


def bundle(
    *, client_id: str = "", client_secret: str = "", rehearse_writes: bool = True
) -> ProviderBundle:
    """Everything Google can do today, in one object for the registry.

    ``rehearse_writes`` sends every write as a dry run whatever the caller
    asked - Google's own switch, so it can stay on while Meta writes live.
    """
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
