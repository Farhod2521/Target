"""The eleven things the agent knows how to notice.

Rules, not a model. Every proposal on the screen was produced by arithmetic
somebody can read, against thresholds somebody can change, and can be
re-derived from the numbers stored beside it months later. Claude's part
comes after this and is a different job - see ``core.agent.schemas`` - it
reviews the shortlist and writes the sentence; it never invents an entry.

That split is deliberate. A language model asked to decide what to do with
an advertising budget can produce a fluent recommendation about an ad set
that does not exist, and no amount of prompting removes the possibility. A
rule cannot: it is handed a list of real ad sets and returns a subset of
them. What a rule cannot do is explain itself to a shop owner in their own
language, which is exactly what the model is for.

Nothing here reads a clock. Cooldown arrives as a set of ids that are off
limits, because "was this touched recently" is a database question and this
package answers none.

**Nine read figures; two read the provider.** The last two in the table
below are about what the platform itself said - one fault it has stopped an
advert over, one improvement it suggests - and they are the reason
:func:`core.agent.facts.judgeable` has an exception at all. Everything else
here refuses to look at an ad set that is not delivering, which would leave
the agent blind in the one case where a stopped advert is the whole story.

**Every rule says which ad sets it is allowed to see.** Three of them
divide by a lead, and five of the six goals this product now builds cannot
produce one - a website, a purchase, a conversation, a call, an ad bought
to be seen. Left alone, "spent money and brought in nobody" is true of all
of them on their best week, and the agent would spend every night offering
to stop campaigns that are working.

The declaration is on the registration below rather than inside each rule,
and that is the whole design of it: a rule cannot forget a check it is
never shown the subject of, and the next one written has to answer the
question before it can be added to the table at all.
"""

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
    """One rule, and the one thing the scan has to know about it.

    ``needs_leads`` is not a hint. A rule declaring it is handed an account
    with every ad set that cannot bring a lead removed, so the condition is
    enforced by what the rule can see rather than by a line inside it that
    somebody has to remember to write.

    Required rather than defaulted, deliberately. A default would be a
    decision made on behalf of whoever writes the next rule, at the one
    moment they are thinking about it - and the wrong default here is a
    proposal to stop a working campaign.
    """

    code: str
    run: RuleFn
    needs_leads: bool
    # Whether one night's cap applies to it.
    #
    # The cap exists because a screen with fifteen things to approve is a
    # screen nobody approves anything on, and it is the right answer for
    # every rule that proposes an *improvement*: those are opinions about
    # what would be better, they will still hold tomorrow, and the three
    # about the most money are the three worth reading first.
    #
    # A fault is not an opinion. The provider has stopped an advert, and a
    # product that decided the fourth stopped advert could wait until
    # tomorrow would be choosing which of somebody's broken campaigns to
    # mention. There is no ranking to make: all of them.
    #
    # Defaulted, unlike ``needs_leads`` above, and the difference is what
    # the wrong default costs. Forgetting ``needs_leads`` proposes stopping
    # a working campaign; forgetting this one leaves a proposal to be made
    # tomorrow instead of tonight.
    uncapped: bool = False
    # Whether it may only be asked about campaigns this product built.
    #
    # Narrows what the rule is *shown*, so its benchmark is drawn from our
    # campaigns alone. What is *proposed* is ours for every rule, whatever
    # this says - see :func:`scan`.
    #
    # Enforced the way ``needs_leads`` is - by narrowing what the rule is
    # shown, not by a line inside it - see
    # :meth:`core.agent.AccountFacts.only_ours`.
    our_campaigns_only: bool = False


# Every rule, in the order they are asked. The order decides nothing -
# findings are ranked by what they are worth afterwards - but it is the
# order a reader meets them in, so it runs from the most drastic to the
# least.
#
# None needs leads any more. The flag stays for a rule that divides by a lead
# and nothing else: a cost per lead has no meaning where a lead cannot
# happen, and a rule declaring it is handed an account without such groups.
# The three that price a result now read each group's own kind instead.
#
# **No second flag is needed**, and the reason is worth stating once:
# ``needs_leads`` exists because nought leads is
# *ambiguous* - a result on one goal and a definition on another - and a
# rule reading it the wrong way stops a working campaign. Nought
# impressions, no breakdown rows and no reach are not ambiguous. They are
# absence, the values arrive empty, and a rule handed an empty value finds
# nothing. The safe direction is already inside the data.
RULES: tuple[Rule, ...] = (
    # The three that price a result, each against its own kind: a lead group
    # by its leads, a chat group by its conversations - see
    # ``core.agent.rules.money``. Not ``needs_leads`` any more: the kind a
    # group is judged by is decided per group, and a kind nothing counts is
    # never judged.
    Rule(code=WASTING, run=wasting, needs_leads=False),
    # The one rule the provider could not have written divides by a verdict
    # only the advertiser gives - the quality mark on a lead - and the mark
    # is switched off (CLAUDE.md, CPQL). Left registered it would read the
    # marks made before that, and stop a campaign on a verdict nobody can
    # give any more. It comes back with the mark; ``junk`` is kept for it.
    # Rule(code=JUNK, run=junk, needs_leads=True),
    Rule(code=EXPENSIVE, run=expensive, needs_leads=False),
    Rule(code=WINNING, run=winning, needs_leads=False),
    # Not a cost. "Could not spend its budget" is answered by the spend
    # and the allowance, and an awareness campaign can be starved of
    # audience exactly as a lead campaign can.
    # Widening an audience: ours only, like every other rule that
    # replaces a targeting document.
    Rule(code=STARVED, run=starved, needs_leads=False, our_campaigns_only=True),
    # Tired attention has one answer, the brief's: a new advert, said by the
    # morning's frequency levels with their two buttons - see
    # ``core.agent.frequency``. A wider audience beside that message would be
    # a second, different remedy for the same group, so the rule sleeps and
    # its code stays for the rows it wrote, see :data:`DORMANT`.
    # Rule(code=SATURATED, run=saturated, needs_leads=False),
    # The provider's own lead count per age cell, which is nought
    # everywhere on a goal it counts no leads for - and a cut where
    # nothing converted yields no dead slice and no proposal.
    Rule(
        code=NARROW_AUDIENCE,
        run=narrow_audience,
        needs_leads=False,
        our_campaigns_only=True,
    ),
    # The same cut one level down, and the same reason it needs no flag:
    # a goal the provider counts no leads for has no earning rate, every
    # advert falls to ``thin``, and nothing is proposed.
    Rule(code=WEAK_AD, run=weak_ad, needs_leads=False),
    # The other answer to an advert nobody looks at: a new picture rather
    # than a stop. It sees the whole account, because the diagnosis it rests
    # on compares every group with all of it - and it keeps to campaigns
    # this product built by itself, see ``core.agent.rules.refresh``.
    Rule(code=REFRESH_AD, run=refresh_ad, needs_leads=False),
    # Also not a cost, and it must see the whole account: the rule fires
    # only when *every* ad set under a campaign is stopped, and a narrowed
    # account would answer that question about half a campaign.
    Rule(code=IDLE, run=idle, needs_leads=False),
    # The two whose subject is the provider rather than the figures. The
    # first is the reason ``judgeable`` needed an exception - a group the
    # provider stopped is invisible to every rule above it - and it is
    # uncapped because it reports a fact rather than an opinion.
    Rule(
        code=PROVIDER_STOPPED,
        run=provider_stopped,
        needs_leads=False,
        uncapped=True,
        our_campaigns_only=True,
    ),
    # The provider's own advice, which is an improvement like the rest and
    # is capped with them.
    Rule(
        code=PROVIDER_ADVICE,
        run=provider_advice,
        needs_leads=False,
        our_campaigns_only=True,
    ),
    # One advert the provider stopped over its picture, and a picture the
    # account holds to replace it with. A fault, so uncapped; a new creative
    # on somebody else's campaign is more than a stop or a budget, so ours.
    Rule(
        code=BROKEN_PICTURE,
        run=broken_picture,
        needs_leads=False,
        uncapped=True,
        our_campaigns_only=True,
    ),
    # An advert refused under a policy, and new words for it. A fault like
    # the one above, and ours for the same reason.
    Rule(
        code=REFUSED_AD,
        run=refused_ad,
        needs_leads=False,
        uncapped=True,
        our_campaigns_only=True,
    ),
    # A page the adverts send people to does not open: stop the money until
    # it does.
    Rule(code=SITE_DOWN, run=site_down, needs_leads=False, uncapped=True),
)

# The rules about something the provider has stopped. They need no window
# and no agent switched on: what they report is already costing money, and
# they are asked the moment a sync brings the fault in - see
# ``apps.agent.services.propose_fixes``.
FAULT_RULES: frozenset[str] = frozenset(
    {PROVIDER_STOPPED, BROKEN_PICTURE, REFUSED_AD, SITE_DOWN}
)

# Which rules the nightly cap does not apply to. Derived from the table
# above rather than written out again, the same bargain :data:`CODES`
# makes: two lists of the same names is one list and one thing to forget.
UNCAPPED: frozenset[str] = frozenset(rule.code for rule in RULES if rule.uncapped)

# Every rule code, for the Django layer to map to sentences and for a
# migration to check against. A code that is not here has no explanation.
#
# Derived rather than written out. Two lists of the same five names is one
# list and one thing to forget.
#
# A rule taken out of the table while what it divides by is switched off
# keeps its code here: rows it wrote before are still read, and a sentence
# for them is still owed. See :data:`DORMANT`.
DORMANT: tuple[str, ...] = (JUNK, SATURATED)
CODES: tuple[str, ...] = tuple(rule.code for rule in RULES) + DORMANT


def scan(
    *,
    account: AccountFacts,
    policy: Policy,
    blocked: Collection[str] = (),
    refused: Collection[tuple[str, str]] = (),
) -> list[Finding]:
    """Everything the rules notice, ranked and uncapped.

    **One finding per object.** Two rules can fire on the same ad set - a
    starved one that has also spent more than its leads justify - and two
    proposals about the same object are two buttons that contradict each
    other. The one about more money wins, which is the one a person would
    ask about first.

    Ranked by money at stake rather than by rule, so a cap applied
    afterwards does not mean several copies of whichever rule happens to
    run first.

    A rule that divides by a lead never sees an ad set that cannot bring
    one. The narrowing happens here, once, rather than as a condition
    inside three rules - see :class:`Rule`.

    **A change to a part is withdrawn when the whole is being changed.**
    One finding per object cannot catch that on its own: an advert and the
    group it sits in are different ids, so "stop this group" and "stop one
    advert inside it" would both survive and land on one screen as two
    buttons, one of which makes the other pointless. The finding about the
    part goes, whatever it is worth - the reader is being asked about the
    whole thing, and answering that question first is the only order in
    which both answers make sense.

    ``refused`` is narrower than ``blocked`` on purpose: a ``(rule,
    object)`` pair the owner recently said no to. The pair rather than the
    object, because "do not raise this budget" is not "have no opinion
    about this ad set" - a different rule noticing something new about the
    same object is a different question, and it may still be asked. Like
    the cooldown, this arrives as data: how long "recently" lasts is a
    database question and this package answers none.
    """
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

    built = _our_ids(account)
    kept = [
        item
        for item in _without_parts(best)
        if item.ref.id in built or item.parent_id in built
    ]
    return sorted(kept, key=lambda item: (-item.weight, item.ref.id))


def _our_ids(account: AccountFacts) -> frozenset[str]:
    """The groups and campaigns this product built - what may be proposed on.

    **Nothing about a campaign made in Ads Manager is proposed**, a stop
    included: it is its owner's to run there. Filtered after the rules
    rather than by narrowing what they are shown, because most of them
    compare a group with the whole account, hand-made campaigns included -
    and a benchmark drawn from half the account is a different benchmark.
    """
    return frozenset(
        id_
        for item in account.adsets
        if item.is_ours
        for id_ in (item.external_id, item.campaign_external_id)
    )


def _subject(
    *,
    rule: Rule,
    account: AccountFacts,
    on_leads: AccountFacts,
    ours: AccountFacts,
    both: AccountFacts,
) -> AccountFacts:
    """Which narrowing of the account this rule is allowed to be asked about.

    Four, precomputed once for the whole scan rather than per rule: the
    narrowing is a tuple comprehension over every ad set, and eleven rules
    doing it themselves would walk the account eleven times to produce
    four answers.
    """
    if rule.needs_leads and rule.our_campaigns_only:
        return both
    if rule.needs_leads:
        return on_leads
    if rule.our_campaigns_only:
        return ours
    return account


def _without_parts(best: dict[str, Finding]) -> list[Finding]:
    """Drop every finding whose parent is also being proposed about.

    Done after the whole scan rather than inside it, because the order the
    rules run in decides nothing here: the advert's finding may be produced
    before its group's, and a check made as each one arrives would keep
    whichever came first.
    """
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
    """What one night is allowed to propose: the top of :func:`scan`.

    The cap is a product decision, not a limit of the arithmetic. A screen
    with fifteen things to approve is a screen nobody approves anything on,
    and the ones that fall off the bottom are by construction the ones
    about the least money. They will still be there tomorrow.

    **A fault is not capped, and that is the one asymmetry here.** "They
    will still be there tomorrow" is the argument for the cap and it is
    true of every improvement: a budget that should go up will still want
    to go up in the morning. It is not true of an advert the provider has
    switched off, where waiting is the harm - and a cap applied to those
    would mean this product choosing which of somebody's broken campaigns
    to mention. See :data:`UNCAPPED`, which says which rules report facts.

    The order is kept as :func:`scan` ranked it, worst first, with the
    faults in their own places rather than lifted to the top. The screen
    that draws these has three bands of its own and reads the level, not
    the position.
    """
    return cap(
        scan(account=account, policy=policy, blocked=blocked, refused=refused),
        policy=policy,
    )


def cap(found: Iterable[Finding], *, policy: Policy) -> list[Finding]:
    """The top of a ranked list, with every fault kept whatever its place.

    Separate from :func:`find` because the cap belongs to an owner, not to
    an ad account. An owner whose page is paid for out of two accounts has
    one screen to read the night's proposals on, and a cap applied per
    account would put twice as many on it - so the Django layer scans each
    account, puts the findings in one ranking, and asks this once.
    """
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
    """Tonight's version of a proposal made earlier, if it still holds.

    The re-check behind every approval. A stop proposed on Tuesday against
    an ad set with no leads is not a stop to carry out on Thursday if it
    brought one in on Wednesday - and the honest way to know is to run the
    same rules against today's account and look for the same conclusion.

    Matched on rule and object, not on the payload. A budget rule that now
    proposes a slightly different figure is the same finding with fresher
    arithmetic - and it is the fresher one that should be carried out,
    which is why this returns the finding rather than a boolean.
    """
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
