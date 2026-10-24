"""The rule the provider could never write."""

from adskit import ExternalRef

from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable

JUNK = "junk"

MIN_EXPECTED_QUALIFIED = 3


def junk(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """It brings people in, and the owner wants none of them - stop it."""
    share = account.lead_totals.quality_share
    if share <= 0:
        return []

    found: list[Finding] = []
    for item in account.adsets:
        if not judgeable(item, policy) or item.totals.qualified > 0:
            continue
        expected = item.totals.leads * share / 100
        if expected < MIN_EXPECTED_QUALIFIED:
            continue

        found.append(
            Finding(
                kind="pause",
                rule=JUNK,
                ref=_ref(account, item),
                weight=item.totals.spend_minor,
                evidence={
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    "leads": item.totals.leads,
                    "qualified": item.totals.qualified,
                    "account_quality_share": share,
                    "expected_qualified": int(expected),
                    "currency": account.currency,
                },
            )
        )

    return found


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = ["JUNK", "MIN_EXPECTED_QUALIFIED", "junk"]
