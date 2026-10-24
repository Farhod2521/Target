"""Which implementation answers for which provider.

This module is the *only* place in the codebase allowed to look at a
provider name and decide something. Everywhere else asks for a bundle and
calls it. The moment ``if provider == "meta"`` appears in a service, a task
or a template, the abstraction has stopped paying for itself.

Registration happens in the application layer, not here: this package must
not import metaads, or it would depend on the thing that depends on it.
"""

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
    """Everything one provider can do, in one object.

    All seven ports are required. A provider that cannot yet do one of them
    supplies an implementation that raises - which fails loudly at the call
    site, rather than quietly at attribute lookup somewhere unrelated.

    ``money`` is the exception to that rule and is deliberately not a
    fifth port. It carries no behaviour and needs no connection: it is the
    provider's own arithmetic for a currency's smallest unit, which is
    knowable while every port on this bundle is refusing calls. A port
    method would have made it unanswerable exactly when a half-built
    provider is being wired up, and the honest answer there is the
    standard's, not an exception.

    Defaulted for the same reason: a provider that has said nothing about
    money counts it the way ISO 4217 does, which is true of most of them
    and is the assumption every unverified currency already carries.
    """

    campaigns: CampaignControlPort
    metrics: MetricsPort
    leads: LeadSourcePort
    # Who one ad set is shown to: words turned into targetable ids, a size
    # measured, a spec replaced.
    audiences: AudiencePort
    # The audiences the advertiser owns, as objects: created, filled,
    # watched while the provider processes them, deleted. Undefaulted like
    # the four above it - a provider that cannot do this yet says so by
    # name through ``Unavailable``, which is cheaper than a bundle that
    # silently answers for a capability nobody implemented.
    audience_sources: AudienceSourcePort
    # The one port that carries an answer back to the provider: what became
    # of a lead it delivered. Undefaulted like the five above, and the
    # reason is sharper here than anywhere else - a bundle that silently
    # accepted verdicts and sent them nowhere would leave an account
    # optimising for form submissions while every screen in this product
    # reported a cost per qualified lead. Nothing would look broken.
    conversions: ConversionPort
    # How a person's consent becomes a token. Undefaulted like the rest: a
    # provider nobody can connect to is not one any screen should offer.
    connect: ConnectPort
    money: MoneyRules = ISO_MONEY


_PROVIDERS: dict[str, ProviderBundle] = {}


def register(name: str, bundle: ProviderBundle) -> None:
    """Make a provider available under ``name``.

    Called from the Django app config's ``ready()``. Re-registering the same
    name overwrites, so a double import during autoreload is harmless.
    """
    _PROVIDERS[name] = bundle


def get(name: str) -> ProviderBundle:
    """The bundle registered under ``name``.

    Raises rather than returning None: a missing provider is a startup bug,
    and a None here would surface as an AttributeError several frames later
    with nothing pointing at the cause.
    """
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise ProviderNotRegistered(
            f"no provider registered as {name!r}; registered: {sorted(_PROVIDERS)}"
        ) from None


def clear() -> None:
    """Empty the registry. Tests only - keeps one test's fake out of the next."""
    _PROVIDERS.clear()
