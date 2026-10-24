"""Which adapter answers for which provider."""

from paykit.errors import ProviderNotRegistered
from paykit.ports import PaymentPort
from paykit.refs import ProviderName

_PROVIDERS: dict[str, PaymentPort] = {}


def register(name: ProviderName, adapter: PaymentPort) -> None:
    """Make a provider available under ``name``."""
    _PROVIDERS[name] = adapter


def get(name: ProviderName) -> PaymentPort:
    """The adapter registered under ``name``."""
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise ProviderNotRegistered(
            f"no payment provider registered as {name!r}; "
            f"registered: {sorted(_PROVIDERS)}"
        ) from None


def available() -> tuple[ProviderName, ...]:
    """Every provider this deployment can actually take money through."""
    return tuple(ProviderName(name) for name in sorted(_PROVIDERS))


def clear() -> None:
    """Empty the registry. Tests only - keeps one test's fake out of the next."""
    _PROVIDERS.clear()


__all__ = ["available", "clear", "get", "register"]
