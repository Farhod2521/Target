"""Rules about whether an ad set is being shown at all.

The other two of the five, and they answer a question the cost rules
cannot: an ad set that spends a third of its budget is not expensive and it
is not cheap, it is barely running - and every figure derived from it is
too thin to mean anything.

**Neither declares ``needs_leads``**, and that is the other half of the
same decision the cost rules make. Nothing here divides by a lead: how much
of its allowance an ad set managed to spend means the same on a call
campaign as on a form, and a campaign the agent switched off is switched
off whatever it was selling.
"""

from adskit import ExternalRef

from core.agent.benchmark import lead_cost, lead_count
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable
from core.agent.guardrails import ACTIVE, PAUSED
from core.agent.widen import widen

STARVED = "starved"
IDLE = "idle"


def starved(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """Cannot spend its budget - widen the audience, not the money.

    The one rule where more money is the wrong answer. The ad set is not
    losing an auction it can afford to bid higher in; it is running out of
    people to show the ad to, and the provider stops delivering long before
    the budget is gone. Raising the figure changes nothing at all.

    One step outward per proposal - see :mod:`core.agent.widen`. A run that
    doubles the radius and finds it was enough never gets to the interests,
    which is the point of proposing the gentlest change that could work
    rather than the change most likely to work.
    """
    found: list[Finding] = []

    for item in account.adsets:
        if not judgeable(item, policy) or not item.daily_budget_minor:
            continue
        # The share is against today's budget, which is not the one the
        # window ran on when it was moved inside it.
        if item.budget_moved or item.spend_share > policy.starved_share_pct:
            continue

        wider = widen(item.targeting)
        if wider is None:
            # Already showing to everyone this spec can reach. Nothing to
            # propose, and saying so is not the agent's job: a suggestion
            # that amounts to "we tried" is noise on a screen whose whole
            # value is that everything on it is worth reading.
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
    """A campaign the agent stopped completely - offer to start it again.

    Narrow on purpose, and the narrowness is the rule. It fires only when
    every ad set under an active campaign is stopped *and the last one to
    stop was stopped by us*. An owner who paused their own campaign made a
    decision - the shop is closed, the stock ran out, the season is over -
    and a product that proposes undoing it every night has mistaken its own
    opinion for information.

    So this exists to undo one specific thing: an agent that stopped an
    account's last working ad set and left it spending nothing.
    """
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
    """The one worth starting again, out of several that were stopped.

    Cheapest lead wins, counted the larger way the cost rules count it.
    That is a question about an ad set that could have brought a lead, and
    where one could and did not, the question genuinely has no answer worth
    guessing at - none of them earned a restart and proposing one would be
    picking at random. Not the cheapest *qualified* lead: the owner's
    quality mark is switched off (CLAUDE.md, CPQL), and ranking by marks
    made before that would restart a campaign on a verdict nobody gives.

    **The third pass is for the ad sets where nought was never a failure.**
    A call campaign, a website campaign and an ad bought to be seen have no
    cost per lead and never will, so without it they fall through every
    branch above to ``None`` - which would leave the agent able to stop one
    of them and unable to offer it back, the only object in this product it
    could break in one direction only. Among those, the one that spent the
    most is the one that was actually running.

    Ordered rather than merged, and the order is the point: a lead ad set
    with no leads must not win a restart on the strength of having spent
    the money that proved it was not working.
    """
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
