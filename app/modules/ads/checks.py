"""The one setting that can silence this product, said out loud at startup.

``ADS_DRY_RUN`` defaults to on, and that default is right: forgetting it must
not spend a customer's money. What is wrong is that leaving it on has no
symptom. A rehearsed launch succeeds, the screen says the campaign is ready,
mirror rows appear with stand-in ids, and the advertiser waits for leads that
cannot arrive.

So a deployment that is not in debug logs a warning when it starts - the API
and the worker both, since the worker is where launches are carried out. A
warning and not a refusal: a developer's machine is meant to be in this state.
``DEBUG`` is the whole of the test, as it was in Django's ``apps.ads.checks``.
"""

import logging

from app.common.env import Env

logger = logging.getLogger(__name__)


def rehearsing(settings: Env) -> list[str]:
    """The dry-run switches left on in a deployment that is not in debug."""
    if settings.debug:
        return []
    switches = {
        "ADS_DRY_RUN": settings.ads_dry_run,
        "GOOGLE_ADS_DRY_RUN": settings.google_ads_dry_run,
    }
    return [name for name, on in switches.items() if on]


def warn_if_rehearsing(settings: Env) -> None:
    switches = rehearsing(settings)
    if switches:
        logger.warning(
            "%s %s on, so nothing this deployment creates reaches the ad "
            "account: launches rehearse, report success and record stand-in "
            "ids. Set it to false in the environment file, or leave it on "
            "deliberately.",
            " and ".join(switches),
            "is" if len(switches) == 1 else "are",
        )
