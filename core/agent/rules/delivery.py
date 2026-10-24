"""Rules about whether an ad set is being shown at all."""

from adskit import ExternalRef

from core.agent.benchmark import lead_cost, lead_count
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable
from core.agent.guardrails import ACTIVE, PAUSED
from core.agent.widen import widen

STARVED = "starved"
IDLE = "idle"


def starved(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Cannot spend its budget - widen the audience, not the money."""
    found: list[Finding] = []

    for item in account.adsets:
        if not judgeable(item, policy) or not item.daily_budget_minor:
            continue
        if item.budget_moved or item.spend_share > policy.starved_share_pct:
            continue

        wider = widen(item.targeting)
        if wider is None:
            continue

        found.append(
            Finding(
                kind="swap_targeting",
                rule=STARVED,
                ref=_ref(account, item),
                weight=max(0, item.budgeted_minor - item.totals.spend_minor),
                evidence={
                    "days": item.days_with_spend,
                    "spend_share": item.spend_share,
                    "spend_minor": item.totals.spend_minor,
                    "budgeted_minor": item.budgeted_minor,
                    "impressions": item.totals.impressions,
                    "step": wider.step,
                    "currency": account.currency,
                    **wider.detail,
                },
                payload={"targeting": wider.targeting, "step": wider.step},
            )
        )

    return found


def idle(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """A campaign the agent stopped completely - offer to start it again."""
    found: list[Finding] = []
    seen: set[str] = set()

    for item in account.adsets:
        campaign = item.campaign_external_id
        if not campaign or campaign in seen:
            continue
        seen.add(campaign)

        group = account.in_campaign(campaign)
        if any(member.delivery == ACTIVE for member in group):
            continue

        candidate = _best(
            [
                member
                for member in group
                if member.delivery == PAUSED
                and member.stopped_by_agent
                and member.days_with_spend >= policy.min_days
            ]
        )
        if candidate is None:
            continue

        cost = lead_cost(candidate.totals)
        found.append(
            Finding(
                kind="resume",
                rule=IDLE,
                ref=_ref(account, candidate),
                weight=candidate.totals.spend_minor,
                evidence={
                    "campaign_external_id": campaign,
                    "stopped_in_campaign": len(group),
                    "days": candidate.days_with_spend,
                    "spend_minor": candidate.totals.spend_minor,
                    "leads": lead_count(candidate) if candidate.counts_leads else None,
                    "cpl_minor": int(cost) if candidate.counts_leads and cost else None,
                    "currency": account.currency,
                },
            )
        )

    return found


def _best(candidates: list[AdSetFacts]) -> AdSetFacts | None:
    """The one worth starting again, out of several that were stopped."""
    if not candidates:
        return None

    by_lead = [
        (cost, item)
        for cost, item in ((lead_cost(item.totals), item) for item in candidates)
        if cost is not None and item.counts_leads
    ]
    if by_lead:
        return min(by_lead, key=lambda pair: pair[0])[1]

    without_leads = [item for item in candidates if not item.counts_leads]
    if without_leads:
        return max(without_leads, key=lambda item: item.totals.spend_minor)

    return None


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = ["IDLE", "STARVED", "idle", "starved"]
