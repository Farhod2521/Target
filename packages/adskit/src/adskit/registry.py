"""Which implementation answers for which provider."""

from dataclasses import dataclass

from adskit.errors import ProviderNotRegistered
from adskit.money import ISO_MONEY, MoneyRules
from adskit.ports import (
    AudiencePort,
    AudienceSourcePort,
    CampaignControlPort,
    ConnectPort,
    ConversionPort,
    LeadSourcePort,
    MetricsPort,
)


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """Everything one provider can do, in one object."""

    campaigns: CampaignControlPort
    metrics: MetricsPort
    leads: LeadSourcePort
    audiences: AudiencePort
    audience_sources: AudienceSourcePort
    conversions: ConversionPort
    connect: ConnectPort
    money: MoneyRules = ISO_MONEY


_PROVIDERS: dict[str, ProviderBundle] = {}


def register(name: str, bundle: ProviderBundle) -> None:
    """Make a provider available under ``name``."""
    _PROVIDERS[name] = bundle


def get(name: str) -> ProviderBundle:
    """The bundle registered under ``name``."""
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise ProviderNotRegistered(
            f"no provider registered as {name!r}; registered: {sorted(_PROVIDERS)}"
        ) from None


def clear() -> None:
    """Empty the registry. Tests only - keeps one test's fake out of the next."""
    _PROVIDERS.clear()
