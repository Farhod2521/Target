"""Rules about what an ad set costs, in the result it was bought for."""

from dataclasses import dataclass

from adskit import ExternalRef

from core.agent.benchmark import (
    family_of,
    lead_count,
    peers,
    peers_lead_cost,
    per_of,
    result_cost,
    result_count,
)
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable

WASTING = "wasting"
WINNING = "winning"
EXPENSIVE = "expensive"

MIN_RESULTS_FOR_A_PRICE = 5
FAR_DEARER_PCT = 300


@dataclass(frozen=True, slots=True)
class _Priced:
    """One group's result against what that result usually costs here."""

    family: str
    count: int
    usual: int
    per: int

    def cost_of(self, spend_minor: int) -> int | None:
        return result_cost(
            spend_minor=spend_minor, count=self.count, family=self.family
        )


def _priced(item: AdSetFacts, *, account: AccountFacts) -> _Priced | None:
    """The group's count and the usual price of its kind, or ``None``."""
    family = family_of(item)
    usual: int | None
    if family == "lead":
        usual = peers_lead_cost(account.lead_totals, item)
        count: int | None = lead_count(item)
    else:
        usual = peers(account.adsets, item).cost_minor
        count = result_count(item)
    if usual is None and (own := account.usual.get(family)) is not None:
        usual = own.cost_minor
    if usual is None or count is None:
        return None
    return _Priced(family=family, count=count, usual=int(usual), per=per_of(family))


def wasting(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Spent real money and produced no result at all - stop it."""
    found: list[Finding] = []
    for item in account.adsets:
        priced = _priced(item, account=account)
        if priced is None or not judgeable(item, policy) or priced.count != 0:
            continue
        spend = item.totals.spend_minor
        if spend * priced.per < priced.usual * policy.waste_multiple:
            continue
        found.append(
            Finding(
                kind="pause",
                rule=WASTING,
                ref=_ref(account, item),
                weight=spend,
                evidence={
                    "days": item.days_with_spend,
                    "spend_minor": spend,
                    "impressions": item.totals.impressions,
                    **_result_evidence(item, priced),
                    "multiple": policy.waste_multiple,
                    "currency": account.currency,
                },
            )
        )
    return found


def winning(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Cheap, proven, and held back by its own budget - give it more."""
    found: list[Finding] = []
    for item in account.adsets:
        budget = item.daily_budget_minor
        priced = _priced(item, account=account)
        if priced is None or not judgeable(item, policy) or not budget:
            continue
        if item.learning_limited:
            continue
        if priced.count < MIN_RESULTS_FOR_A_PRICE:
            continue
        spend = item.totals.spend_minor
        if (
            spend * priced.per * 100
            > priced.usual * priced.count * policy.win_share_pct
        ):
            continue
        if item.budget_moved or item.spend_share < policy.constrained_share_pct:
            continue

        raised = _stepped(budget, policy.budget_step_pct)
        found.append(
            Finding(
                kind="increase_budget",
                rule=WINNING,
                ref=_ref(account, item),
                weight=(raised - budget) * account.window_days,
                evidence=_cost_evidence(account, item, priced)
                | {"from_minor": budget, "to_minor": raised},
                payload={"daily_budget_minor": raised},
            )
        )

    return found


def expensive(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Leads far dearer than this account normally pays - spend less on it."""
    found: list[Finding] = []
    for item in account.adsets:
        budget = item.daily_budget_minor
        priced = _priced(item, account=account)
        if priced is None or not judgeable(item, policy) or not budget:
            continue
        if item.learning_limited:
            continue
        count = priced.count
        if count < 1:
            continue
        spend = item.totals.spend_minor
        bar = (
            policy.lose_share_pct
            if count >= MIN_RESULTS_FOR_A_PRICE
            else FAR_DEARER_PCT
        )
        if spend * priced.per * 100 < priced.usual * count * bar:
            continue

        lowered = _stepped(budget, -policy.budget_step_pct)
        if item.floor_minor > 0 and lowered < item.floor_minor:
            continue

        found.append(
            Finding(
                kind="decrease_budget",
                rule=EXPENSIVE,
                ref=_ref(account, item),
                weight=max(0, spend - count * priced.usual // priced.per),
                evidence=_cost_evidence(account, item, priced)
                | {"from_minor": budget, "to_minor": lowered},
                payload={"daily_budget_minor": lowered},
            )
        )

    return found


def _cost_evidence(
    account: AccountFacts, item: AdSetFacts, priced: _Priced
) -> dict[str, object]:
    """The numbers both budget rules show their working with."""
    return {
        "days": item.days_with_spend,
        "spend_minor": item.totals.spend_minor,
        **_result_evidence(item, priced),
        "spend_share": item.spend_share,
        "currency": account.currency,
    }


def _result_evidence(item: AdSetFacts, priced: _Priced) -> dict[str, object]:
    """The group's result and its price, in the words of its own kind."""
    cost = priced.cost_of(item.totals.spend_minor)
    if priced.family == "lead":
        return {
            "leads": priced.count,
            "cpl_minor": int(cost) if cost is not None else None,
            "account_cpl_minor": priced.usual,
        }
    return {
        "outcome": priced.family,
        "results": priced.count,
        "cost_minor": cost,
        "account_cost_minor": priced.usual,
    }


def _stepped(budget_minor: int, percent: int) -> int:
    """A budget moved by a percentage, still a whole number of minor units."""
    return max(1, round(budget_minor * (100 + percent) / 100))


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = [
    "EXPENSIVE",
    "FAR_DEARER_PCT",
    "MIN_RESULTS_FOR_A_PRICE",
    "WASTING",
    "WINNING",
    "expensive",
    "wasting",
    "winning",
]
