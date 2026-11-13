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
from app.modules.billing.constants import MULTICARD_TEST_NAME

logger = logging.getLogger(__name__)

# Multicard's sandbox beside the live shop: nothing is charged there, and its
# test card pays. Only the accounts below are ever sent to it - a sandbox
# payment opens a real subscription, so nobody else may reach it.
MULTICARD_TEST = ProviderName(MULTICARD_TEST_NAME)
TEST_EMAILS: frozenset[str] = frozenset({"rahimovarslonbek997@gmail.com"})
REQUIRED: dict[ProviderName, tuple[str, ...]] = {
    PAYME: ("payme_merchant_id", "payme_key"),
    CLICK: ("click_service_id", "click_merchant_id", "click_secret_key"),
    PAYNET: ("paynet_username", "paynet_password", "paynet_service_id"),
    MULTICARD_TEST: (
        "multicard_test_application_id",
        "multicard_test_secret",
        "multicard_test_store_id",
        "multicard_callback_url",
        "multicard_ofd_mxik",
        "multicard_ofd_package_code",
    ),
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


def _multicard_test() -> PaymentPort | None:
    if not configured(provider=MULTICARD_TEST):
        return None
    return MulticardAdapter(
        name=MULTICARD_TEST,
        client=MulticardClient(
            base_url=settings.multicard_test_api_url,
            application_id=settings.multicard_test_application_id,
            secret=settings.multicard_test_secret,
        ),
        store_id=settings.multicard_test_store_id,
        secret=settings.multicard_test_secret,
        callback_url=sandbox_callback_url(settings.multicard_callback_url),
        decimal_places=decimal_places(settings.billing_currency),
        ofd_mxik=settings.multicard_ofd_mxik,
        ofd_package_code=settings.multicard_ofd_package_code,
        ofd_name=settings.multicard_ofd_name,
        ofd_vat=settings.multicard_ofd_vat,
        ofd_tin=settings.multicard_ofd_tin,
    )


def sandbox_callback_url(live: str) -> str:
    """The sandbox's callback: the live one, under the sandbox's own name."""
    return live.rstrip("/").removesuffix(MULTICARD) + MULTICARD_TEST


def is_tester(*, email: str | None) -> bool:
    return (email or "").strip().casefold() in TEST_EMAILS


def provider_for(*, provider: str, email: str | None) -> str | None:
    """The provider this payer really pays through, or ``None`` if not allowed.

    A test account that picks Rahmat pays in the sandbox, when one is set up;
    the sandbox asked for by anyone else is refused.
    """
    tester = is_tester(email=email)
    if provider == MULTICARD_TEST:
        return provider if tester else None
    if provider == MULTICARD and tester and MULTICARD_TEST in registry.available():
        return MULTICARD_TEST
    return provider


BUILDERS: tuple[tuple[ProviderName, Callable[[], PaymentPort | None]], ...] = (
    (PAYME, _payme),
    (CLICK, _click),
    (PAYNET, _paynet),
    (MULTICARD, _multicard),
    (MULTICARD_TEST, _multicard_test),
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
