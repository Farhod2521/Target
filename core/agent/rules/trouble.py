"""The rule whose subject is the provider rather than the figures.

Every other rule in this package reads numbers and proposes a better bet.
This one reads what the platform itself said about something it has
broken off, and it is what keeps the agent from being blind at the worst
moment. The provider's advice about what could be better is not read here
at all (TZ 7.4): it is neither shown nor acted on - see
:mod:`app.modules.ads.recommendations`.

**The exception it needs is structural, not an oversight.**
:func:`core.agent.facts.judgeable` requires an ad set to be *delivering*
before any rule forms an opinion about it, which is right for all the
others: a stopped ad set has no figures worth reading and an opinion drawn
from a week of noughts would be an opinion about the stopping. But a group
the provider switched off over a dead audience is exactly the case where
this product has something urgent and specific to say, and it is the one
case every other rule cannot see. :func:`core.agent.facts.troubled` is the
exception, and it exists for this file only.

**It does not declare ``needs_leads``.** Nothing here divides by a lead. A
broken audience is broken on a call campaign and on a form campaign alike.
"""

from adskit import ExternalRef

from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, troubled
from core.agent.repair import repair

PROVIDER_STOPPED = "provider_stopped"


def provider_stopped(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """The provider stopped this group over a dead audience - take it out.

    The only proposal in this package that undoes a fault rather than
    improving a result, and the only one whose weight is not a measurement
    of what happened but of what has stopped happening.

    **Fires only where there is something to press.** A fault this product
    cannot repair - an audience blocked on the exclusion side, a fault
    about something other than an audience, a code nobody here recognises
    - produces no proposal, and that is deliberate rather than a gap: the
    line is already on the owner's waiting list in the provider's own
    words with the assistant a button away, and a card offering a change
    that would not fix it is worse than no card.
    """
    found: list[Finding] = []

    for item in account.adsets:
        if not troubled(item):
            continue

        fixed = repair(item.targeting, unusable=item.unusable_audience_ids)
        if fixed is None:
            continue

        found.append(
            Finding(
                kind="drop_audience",
                rule=PROVIDER_STOPPED,
                ref=_ref(account, item),
                # What has stopped moving. The window's spend where there
                # is any - this group was working until the audience broke
                # - and a day of its budget where the fault arrived before
                # the figures did. Never nought: a stopped group must not
                # rank below a group that is merely expensive.
                weight=max(
                    item.totals.spend_minor,
                    item.daily_budget_minor or 0,
                ),
                evidence={
                    "issue_codes": list(item.issue_codes),
                    # The count on the card, the ids beside it for the
                    # replay. A provider id is not a phrase anybody
                    # recognises as their own audience, and the name is on
                    # a row the Django layer already holds.
                    "dropped_audiences": len(fixed.dropped),
                    "dropped_audience_ids": list(fixed.dropped),
                    # How many of the advertiser's own lists the group is
                    # still aimed at. Nought is the case the card has to
                    # say out loud: the only list named is the one that
                    # broke, so the advert will be shown to anybody the
                    # rest of the targeting allows.
                    "kept_audiences": fixed.kept,
                    "delivery": item.delivery,
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    "currency": account.currency,
                },
                payload={"targeting": fixed.targeting},
            )
        )

    return found


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = [
    "PROVIDER_STOPPED",
    "provider_stopped",
]
