"""The registry is the only place allowed to turn a provider name into code.

If these tests ever need an `if provider == ...` to pass, the abstraction has
already failed somewhere else.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from adskit import (
    ActionResult,
    AudiencePort,
    CampaignControlPort,
    ExternalRef,
    InterestDTO,
    LeadSourcePort,
    LocationDTO,
    MetricsPort,
    ProviderBundle,
    ProviderNotRegistered,
    ReachDTO,
    TraitKind,
    Unavailable,
)
from adskit import registry as registry_module


class _Audiences:
    """Minimal stand-in: enough to satisfy the protocol, nothing more."""

    def find_interests(self, *, names: list[str], token: str) -> list[InterestDTO]:
        return []

    def find_traits(
        self, *, kind: TraitKind, names: list[str], token: str
    ) -> list[InterestDTO]:
        return []

    def find_locations(
        self, *, query: str, country_code: str, token: str
    ) -> list[LocationDTO]:
        return []

    def estimate_reach(
        self,
        *,
        account: ExternalRef,
        targeting: dict[str, Any],
        optimization_goal: str,
        token: str,
    ) -> ReachDTO:
        return ReachDTO()

    def apply(
        self,
        *,
        ref: ExternalRef,
        targeting: dict[str, Any],
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        return ActionResult(ok=True, ref=ref, applied=targeting, dry_run=dry_run)


def _bundle() -> ProviderBundle:
    return ProviderBundle(
        campaigns=object(),  # type: ignore[arg-type]
        metrics=object(),  # type: ignore[arg-type]
        leads=object(),  # type: ignore[arg-type]
        audiences=_Audiences(),
        # A stand-in that refuses, which is what a real half-built provider
        # supplies. Passing ``object()`` here would pass this test and hide
        # the thing the fifth port was added with: a bundle is complete from
        # the first day or it fails at the call site.
        audience_sources=Unavailable(provider="test", port="audience sources"),
        conversions=Unavailable(provider="test", port="conversions"),
        connect=Unavailable(provider="test", port="connect"),
    )


@pytest.fixture(autouse=True)
def _empty_registry() -> Iterator[None]:
    """One test's fake provider must not leak into the next."""
    registry_module.clear()
    yield
    registry_module.clear()


def test_registered_provider_is_returned() -> None:
    registry_module.register("meta", _bundle())

    assert registry_module.get("meta").audiences is not None


def test_unknown_provider_raises_rather_than_returning_none() -> None:
    """A None here would surface as an AttributeError frames later."""
    registry_module.register("meta", _bundle())

    with pytest.raises(ProviderNotRegistered) as exc:
        registry_module.get("google")

    # The message names what *is* registered: the usual cause is a lookup
    # that ran before the app config registering the bundle.
    assert "google" in str(exc.value)
    assert "meta" in str(exc.value)


def test_re_registering_overwrites() -> None:
    """Autoreload imports the app config twice; that must be harmless."""
    registry_module.register("meta", _bundle())
    second = _bundle()
    registry_module.register("meta", second)

    assert registry_module.get("meta") is second


@pytest.mark.parametrize(
    "port",
    [CampaignControlPort, MetricsPort, LeadSourcePort, AudiencePort],
)
def test_ports_are_runtime_checkable(port: type) -> None:
    """Adapters are checked against the protocol, not against a base class."""
    assert not isinstance(object(), port)


def test_adapter_satisfying_a_port_passes_the_check() -> None:
    assert isinstance(_Audiences(), AudiencePort)
