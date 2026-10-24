"""The eleven things the agent knows how to notice."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Protocol

from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts
from core.agent.rules.audience import (
    NARROW_AUDIENCE,
    SATURATED,
    narrow_audience,
    saturated,
)
from core.agent.rules.creative import WEAK_AD, weak_ad
from core.agent.rules.delivery import IDLE, STARVED, idle, starved
from core.agent.rules.faults import (
    BROKEN_PICTURE,
    REFUSED_AD,
    SITE_DOWN,
    broken_picture,
    refused_ad,
    site_down,
)
from core.agent.rules.money import (
    EXPENSIVE,
    WASTING,
    WINNING,
    expensive,
    wasting,
    winning,
)
from core.agent.rules.quality import JUNK, junk
from core.agent.rules.refresh import REFRESH_AD, refresh_ad
from core.agent.rules.trouble import (
    PROVIDER_ADVICE,
    PROVIDER_STOPPED,
    provider_advice,
    provider_stopped,
)


class RuleFn(Protocol):
    """What every rule looks like from the outside."""

    def __call__(self, *, account: AccountFacts, policy: Policy) -> list[Finding]: ...


@dataclass(frozen=True, slots=True)
class Rule:
    """One rule, and the one thing the scan has to know about it."""

    code: str
    run: RuleFn
    needs_leads: bool
    uncapped: bool = False
    our_campaigns_only: bool = False


RULES: tuple[Rule, ...] = (
    Rule(code=WASTING, run=wasting, needs_leads=False),
    Rule(code=EXPENSIVE, run=expensive, needs_leads=False),
    Rule(code=WINNING, run=winning, needs_leads=False),
    Rule(code=STARVED, run=starved, needs_leads=False, our_campaigns_only=True),
    Rule(code=SATURATED, run=saturated, needs_leads=False),
    Rule(
        code=NARROW_AUDIENCE,
        run=narrow_audience,
        needs_leads=False,
        our_campaigns_only=True,
    ),
    Rule(code=WEAK_AD, run=weak_ad, needs_leads=False),
    Rule(code=REFRESH_AD, run=refresh_ad, needs_leads=False),
    Rule(code=IDLE, run=idle, needs_leads=False),
    Rule(
        code=PROVIDER_STOPPED,
        run=provider_stopped,
        needs_leads=False,
        uncapped=True,
        our_campaigns_only=True,
    ),
    Rule(
        code=PROVIDER_ADVICE,
        run=provider_advice,
        needs_leads=False,
        our_campaigns_only=True,
    ),
    Rule(
        code=BROKEN_PICTURE,
        run=broken_picture,
        needs_leads=False,
        uncapped=True,
        our_campaigns_only=True,
    ),
    Rule(
        code=REFUSED_AD,
        run=refused_ad,
        needs_leads=False,
        uncapped=True,
        our_campaigns_only=True,
    ),
    Rule(code=SITE_DOWN, run=site_down, needs_leads=False, uncapped=True),
)

FAULT_RULES: frozenset[str] = frozenset(
    {PROVIDER_STOPPED, BROKEN_PICTURE, REFUSED_AD, SITE_DOWN}
)

UNCAPPED: frozenset[str] = frozenset(rule.code for rule in RULES if rule.uncapped)

DORMANT: tuple[str, ...] = (JUNK,)
CODES: tuple[str, ...] = tuple(rule.code for rule in RULES) + DORMANT


def scan(
    *,
    account: AccountFacts,
    policy: Policy,
    blocked: Collection[str] = (),
    refused: Collection[tuple[str, str]] = (),
) -> list[Finding]:
    """Everything the rules notice, ranked and uncapped."""
    off_limits = set(blocked)
    said_no = set(refused)
    best: dict[str, Finding] = {}
    on_leads = account.only_lead_goals()
    ours = account.only_ours()
    on_leads_and_ours = on_leads.only_ours()

    for rule in RULES:
        subject = _subject(
            rule=rule,
            account=account,
            on_leads=on_leads,
            ours=ours,
            both=on_leads_and_ours,
        )
        for finding in rule.run(account=subject, policy=policy):
            if finding.ref.id in off_limits:
                continue
            if (finding.rule, finding.ref.id) in said_no:
                continue
            current = best.get(finding.ref.id)
            if current is None or finding.weight > current.weight:
                best[finding.ref.id] = finding

    kept = _without_parts(best)
    return sorted(kept, key=lambda item: (-item.weight, item.ref.id))


def _subject(
    *,
    rule: Rule,
    account: AccountFacts,
    on_leads: AccountFacts,
    ours: AccountFacts,
    both: AccountFacts,
) -> AccountFacts:
    """Which narrowing of the account this rule is allowed to be asked about."""
    if rule.needs_leads and rule.our_campaigns_only:
        return both
    if rule.needs_leads:
        return on_leads
    if rule.our_campaigns_only:
        return ours
    return account


def _without_parts(best: dict[str, Finding]) -> list[Finding]:
    """Drop every finding whose parent is also being proposed about."""
    return [
        finding
        for finding in best.values()
        if not finding.parent_id or finding.parent_id not in best
    ]


def find(
    *,
    account: AccountFacts,
    policy: Policy,
    blocked: Collection[str] = (),
    refused: Collection[tuple[str, str]] = (),
) -> list[Finding]:
    """What one night is allowed to propose: the top of :func:`scan`."""
    return cap(
        scan(account=account, policy=policy, blocked=blocked, refused=refused),
        policy=policy,
    )


def cap(found: Iterable[Finding], *, policy: Policy) -> list[Finding]:
    """The top of a ranked list, with every fault kept whatever its place."""
    allowance = max(0, policy.max_per_run)
    chosen: list[Finding] = []
    for finding in found:
        if finding.rule in UNCAPPED:
            chosen.append(finding)
            continue
        if allowance <= 0:
            continue
        allowance -= 1
        chosen.append(finding)
    return chosen


def holds(*, finding: Finding, found: Collection[Finding]) -> Finding | None:
    """Tonight's version of a proposal made earlier, if it still holds."""
    for item in found:
        if item.rule == finding.rule and item.ref == finding.ref:
            return item
    return None


__all__ = [
    "BROKEN_PICTURE",
    "CODES",
    "DORMANT",
    "EXPENSIVE",
    "FAULT_RULES",
    "IDLE",
    "JUNK",
    "NARROW_AUDIENCE",
    "PROVIDER_ADVICE",
    "PROVIDER_STOPPED",
    "REFRESH_AD",
    "REFUSED_AD",
    "RULES",
    "SATURATED",
    "SITE_DOWN",
    "STARVED",
    "UNCAPPED",
    "WASTING",
    "WEAK_AD",
    "WINNING",
    "Rule",
    "RuleFn",
    "cap",
    "expensive",
    "find",
    "holds",
    "idle",
    "junk",
    "narrow_audience",
    "provider_advice",
    "provider_stopped",
    "saturated",
    "scan",
    "starved",
    "wasting",
    "weak_ad",
    "winning",
]
