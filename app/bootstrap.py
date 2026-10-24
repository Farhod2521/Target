"""What Django's AppConfig.ready() did: put the provider adapters in their registries."""

from adskit import registry
from googleadskit import PROVIDER as GOOGLE
from googleadskit.adapter import bundle as google_bundle
from metaads import PROVIDER as META
from metaads.adapter import bundle as meta_bundle

from app.common.config import settings

_done = False


def register_providers() -> None:
    global _done
    if _done:
        return
    registry.register(
        META,
        meta_bundle(app_id=settings.meta_app_id, app_secret=settings.meta_app_secret),
    )
    registry.register(
        GOOGLE,
        google_bundle(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            rehearse_writes=settings.google_ads_dry_run,
        ),
    )
    from app.modules.billing.services.providers import register_payment_providers

    register_payment_providers()
    _done = True
