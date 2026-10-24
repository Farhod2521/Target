"""The two rules whose subject is the provider rather than the figures."""

from adskit import ExternalRef

from core.agent.broaden import broaden
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable, troubled
from core.agent.repair import repair

PROVIDER_STOPPED = "provider_stopped"
PROVIDER_ADVICE = "provider_advice"


def provider_stopped(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """The provider stopped this group over a dead audience - take it out."""
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
                weight=max(
                    item.totals.spend_minor,
                    item.daily_budget_minor or 0,
                ),
                evidence={
                    "issue_codes": list(item.issue_codes),
                    "dropped_audiences": len(fixed.dropped),
                    "dropped_audience_ids": list(fixed.dropped),
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


def provider_advice(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """The platform says it could reach further - let it."""
    found: list[Finding] = []

    for item in account.adsets:
        if "broader_audience" not in item.advice:
            continue
        if not judgeable(item, policy):
            continue

        wider = broaden(item.targeting)
        if wider is None:
            continue

        found.append(
            Finding(
                kind="swap_targeting",
                rule=PROVIDER_ADVICE,
                ref=_ref(account, item),
                weight=max(0, item.budgeted_minor - item.totals.spend_minor),
                evidence={
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    "budgeted_minor": item.budgeted_minor,
                    "spend_share": item.spend_share,
                    "impressions": item.totals.impressions,
                    "changed": list(wider.changed),
                    "currency": account.currency,
                },
                payload={"targeting": wider.targeting},
            )
        )

    return found


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = [
    "PROVIDER_ADVICE",
    "PROVIDER_STOPPED",
    "provider_advice",
    "provider_stopped",
]
