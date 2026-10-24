"""The registry, and the one rule it exists to hold.

Nothing in this product may look at a payment provider's name and decide
something. This is what the alternative looks like when it is confined to
eleven lines - and the tests are about the two behaviours everything else
leans on: a missing provider raises rather than answering ``None``, and
what is *not* registered is not offered.
"""

import pytest
from paykit import ProviderNotRegistered, registry
from paykit.payme import PROVIDER as PAYME
from paykit.payme import PaymeAdapter


@pytest.fixture(autouse=True)
def empty_registry() -> None:
    """One test's adapters must not reach the next one's."""
    registry.clear()


def _adapter() -> PaymeAdapter:
    return PaymeAdapter(merchant_id="m", key="k", account_field="order_id")


def test_an_unregistered_provider_raises() -> None:
    """Never ``None``.

    A callback for a provider nothing is configured under means a
    credential was removed while somebody's money was in flight. An
    ``AttributeError`` several frames later, with nothing pointing at the
    cause, is the outcome this refuses.
    """
    with pytest.raises(ProviderNotRegistered):
        registry.get("payme")


def test_what_is_not_configured_is_not_offered() -> None:
    """The whole enable mechanism, and there is no flag beside it."""
    assert registry.available() == ()
    registry.register(PAYME, _adapter())
    assert registry.available() == (PAYME,)


def test_registering_twice_overwrites() -> None:
    """A double import during autoreload must be harmless."""
    registry.register(PAYME, _adapter())
    second = _adapter()
    registry.register(PAYME, second)

    assert registry.get(PAYME) is second
    assert registry.available() == (PAYME,)
