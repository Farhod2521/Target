import logging
from collections.abc import Callable

from paykit import PaymentPort, ProviderName, registry
from paykit.click import PROVIDER as CLICK
from paykit.click import ClickAdapter
from paykit.multicard import PROVIDER as MULTICARD
from paykit.multicard import MulticardAdapter, MulticardClient
from paykit.payme import PROVIDER as PAYME
from paykit.payme import PaymeAdapter
from paykit.paynet import PROVIDER as PAYNET
from paykit.paynet import PaynetAdapter

from app.common.config import settings
from app.common.money import decimal_places

logger = logging.getLogger(__name__)
REQUIRED: dict[ProviderName, tuple[str, ...]] = {
    PAYME: ("payme_merchant_id", "payme_key"),
    CLICK: ("click_service_id", "click_merchant_id", "click_secret_key"),
    PAYNET: ("paynet_username", "paynet_password", "paynet_service_id"),
    MULTICARD: (
        "multicard_application_id",
        "multicard_secret",
        "multicard_store_id",
        "multicard_callback_url",
        "multicard_ofd_mxik",
        "multicard_ofd_package_code",
    ),
}


def configured(*, provider: ProviderName) -> bool:
    return all(getattr(settings, name, "") for name in REQUIRED[provider])


def _payme() -> PaymentPort | None:
    if not configured(provider=PAYME):
        return None
    return PaymeAdapter(
        merchant_id=settings.payme_merchant_id,
        key=settings.payme_key,
        account_field=settings.payme_account_field,
        checkout_url=settings.payme_checkout_url,
    )


def _click() -> PaymentPort | None:
    if not configured(provider=CLICK):
        return None
    return ClickAdapter(
        service_id=settings.click_service_id,
        merchant_id=settings.click_merchant_id,
        secret_key=settings.click_secret_key,
        decimal_places=decimal_places(settings.billing_currency),
        checkout_url=settings.click_checkout_url,
    )


def _paynet() -> PaymentPort | None:
    if not configured(provider=PAYNET):
        return None
    return PaynetAdapter(
        username=settings.paynet_username,
        password=settings.paynet_password,
        service_id=settings.paynet_service_id,
    )


def _multicard() -> PaymentPort | None:
    if not configured(provider=MULTICARD):
        return None
    return MulticardAdapter(
        client=MulticardClient(
            base_url=settings.multicard_api_url,
            application_id=settings.multicard_application_id,
            secret=settings.multicard_secret,
        ),
        store_id=settings.multicard_store_id,
        secret=settings.multicard_secret,
        callback_url=settings.multicard_callback_url,
        decimal_places=decimal_places(settings.billing_currency),
        ofd_mxik=settings.multicard_ofd_mxik,
        ofd_package_code=settings.multicard_ofd_package_code,
        ofd_name=settings.multicard_ofd_name,
        ofd_vat=settings.multicard_ofd_vat,
        ofd_tin=settings.multicard_ofd_tin,
        allowed_ips=settings.multicard_allowed_ips.split(","),
    )


BUILDERS: tuple[tuple[ProviderName, Callable[[], PaymentPort | None]], ...] = (
    (PAYME, _payme),
    (CLICK, _click),
    (PAYNET, _paynet),
    (MULTICARD, _multicard),
)


def register_payment_providers() -> None:
    live: list[str] = []
    for name, build in BUILDERS:
        adapter = build()
        if adapter is None:
            continue
        registry.register(name, adapter)
        live.append(name)
    logger.info("payment providers registered", extra={"providers": live})
