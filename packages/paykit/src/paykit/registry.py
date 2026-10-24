"""Which adapter answers for which provider.

The only module in this package allowed to look at a provider name and
decide something, exactly as ``adskit.registry`` is on the ads side.
Everywhere else asks for an adapter and calls it - the moment a service, a
task or a template starts comparing a provider name, the abstraction has
stopped paying for itself and the fourth provider becomes a rewrite.

Registration happens in the application layer. This package cannot import
its own adapters here, or the import would run in reverse.

**Registration is also how a provider is switched off.** A deployment with
no Click credentials registers no Click adapter, :func:`available` does not
list it, and no screen offers it. There is no enabled flag to leave in the
wrong position.
"""

from paykit.errors import ProviderNotRegistered
from paykit.ports import PaymentPort
from paykit.refs import ProviderName

_PROVIDERS: dict[str, PaymentPort] = {}


def register(name: ProviderName, adapter: PaymentPort) -> None:
    """Make a provider available under ``name``.

    Called from the Django app config's ``ready()``. Re-registering the
    same name overwrites, so a double import during autoreload is harmless.
    """
    _PROVIDERS[name] = adapter


def get(name: ProviderName) -> PaymentPort:
    """The adapter registered under ``name``.

    Raises rather than answering ``None``. A callback arrives for a
    provider that is not registered in two situations - a deployment that
    forgot a credential, and an invoice created before one was removed -
    and both need to be loud: the alternative is a 404 on a URL somebody's
    money just went through.
    """
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise ProviderNotRegistered(
            f"no payment provider registered as {name!r}; "
            f"registered: {sorted(_PROVIDERS)}"
        ) from None


def available() -> tuple[ProviderName, ...]:
    """Every provider this deployment can actually take money through.

    Sorted, so a pricing screen renders the same order on every process
    and a screenshot from yesterday still matches.
    """
    return tuple(ProviderName(name) for name in sorted(_PROVIDERS))


def clear() -> None:
    """Empty the registry. Tests only - keeps one test's fake out of the next."""
    _PROVIDERS.clear()


__all__ = ["available", "clear", "get", "register"]
