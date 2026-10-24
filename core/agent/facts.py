"""What a decision is allowed to look at.

Everything the rules read arrives here first, as plain values. No ORM row,
no clock, no provider - the same discipline as the rest of ``core``, and
here it buys something specific: a night's decisions can be replayed months
later from the numbers that produced them, which is the only way to answer
"why did it say that" once the account has moved on.

Totals come from :mod:`core.metrics`, which already knows that spend adds
up and a cost per lead does not. Re-deriving CPQL here would be a second
copy of that arithmetic, and the two would disagree the first time one of
them was fixed.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from adskit import ProviderName

from core.agent.ad_facts import AdFacts, LibraryImage
from core.agent.contracts import Policy, ProviderAdvice
from core.agent.funnel import Funnel, Landing
from core.metrics import Outcome, SegmentComparison, SegmentFigures, Totals

# The one delivery state a rule forms opinions about, spelled as the
# domain spells it. Everything else in ``adskit.Delivery`` describes what
# the provider decided rather than what an advertiser wants.
_ACTIVE = "active"

# The states somebody chose: the group's own switch, its campaign's, or an
# end it reached. None of them is the provider breaking something off, and
# a fault reported before the switch went off is history, not news.
_SWITCHED_OFF = frozenset({"paused", "paused_above", "finished"})


def ctr_bp(*, clicks: int, impressions: int) -> int | None:
    """Clicks per ten thousand impressions, or nothing to divide by.

    Ten-thousandths rather than the whole percentages :func:`core.metrics.
    share` deals in, and the reason is the size of the number: a link
    click-through rate lives near one percent, so a figure rounded to the
    percent cannot tell a healthy ad from one that has lost half its pull.

    Here rather than in a rule because two places need the same division -
    the rule that notices a fall and the assessment that grades the
    change - and a ratio computed twice is a ratio that disagrees with
    itself the first time one copy is adjusted.
    """
    if impressions <= 0:
        return None
    return round(clicks * 10_000 / impressions)


@dataclass(frozen=True, slots=True)
class Half:
    """One half of the window, for the questions that need a direction.

    Every other figure here answers "what is this ad set like"; these two
    answer "which way is it going", and that needs the same measurement
    twice with time in between. Split rather than trended over every day,
    because a seven-day window has three or four days a side and a slope
    fitted to that is arithmetic pretending to be evidence.

    ``frequency`` is the **mean of the daily figures**, in hundredths, and
    it cannot be anything else: frequency is impressions over reach, reach
    counts people, and no sum of days deduplicates a person who was there
    on two of them - see :func:`core.metrics.frequency`. So this is "on a
    typical day, each person saw it this many times", which is a smaller
    claim than the campaign-lifetime figure quoted in most advice, and the
    two must not be compared with each other.
    """

    days: int = 0
    impressions: int = 0
    # Clicks that went where the money was sent. The honest CTR's
    # numerator - the headline click count includes caption expansions.
    link_clicks: int = 0
    frequency: int = 0

    @property
    def link_ctr_bp(self) -> int | None:
        """This half's link click-through rate, in ten-thousandths."""
        return ctr_bp(clicks=self.link_clicks, impressions=self.impressions)


@dataclass(frozen=True, slots=True)
class AdSetFacts:
    """One ad set, as the window saw it.

    ``daily_budget_minor`` is ``None`` when the campaign above holds the
    budget instead. That is not zero and not "unlimited": it means this is
    the wrong object to write a budget to, and the budget rules skip it
    rather than writing somewhere that would succeed and change nothing.

    ``stopped_by_agent`` answers one question and only one: may we offer to
    start this again. An ad set the owner stopped is a decision, not a
    problem to solve, and the agent has nothing useful to say about it.

    ``counts_leads`` answers the question every cost rule here depends
    on: whether nought leads is a **result** or a definition. Five of
    the six goals this product now builds - a website, a purchase, a
    conversation, a call, an ad bought to be seen - can never put a row in
    the lead table, so "spent money and brought in nobody" is true of them
    on their best week. See :func:`core.metrics.counts_leads`.
    """

    external_id: str
    campaign_external_id: str
    name: str
    delivery: str
    totals: Totals
    days_with_spend: int = 0
    is_learning: bool = False
    # The provider stopped learning without finishing: too few results a
    # week. Judged like any group, but its price is not a price to move a
    # budget on.
    learning_limited: bool = False
    daily_budget_minor: int | None = None
    # The daily budget was changed during the window - by this product,
    # which is the only change it has a record of. ``budgeted_minor`` then
    # multiplies today's budget over days that ran on another one, and a
    # share read from it says "cannot spend" of a group whose budget was
    # just doubled, or "held back" of one just halved.
    budget_moved: bool = False
    # The provider's own targeting document. Opaque to the rules, read only
    # by ``widen`` - which is the one place in this package that knows what
    # the keys mean.
    targeting: Mapping[str, Any] = field(default_factory=dict)
    # The provider's reported minimum for this object, already adjusted for
    # its optimisation goal by ``core.targeting.daily_floor``. Zero means
    # nobody told us, and switches the floor check off.
    floor_minor: int = 0
    stopped_by_agent: bool = False
    # The window cut in two, for the rules that need a direction rather
    # than a level. Empty halves mean nobody split the window, which
    # switches those rules off rather than letting one read a fall out of
    # two zeroes.
    early: Half = field(default_factory=Half)
    late: Half = field(default_factory=Half)
    # How this ad set's audience divides up - which age and gender cells
    # earned their money and which only spent it.
    #
    # The provider's own lead count is the only basis a segment can have,
    # and that is permanent rather than pending: a lead of ours carries
    # the ad it came from and never the age of the person who filled it
    # in, so no cost per *qualified* lead per segment exists even in
    # principle. See :mod:`core.metrics.segment_compare`.
    #
    # Empty by default, which is the whole guard the segment rules need:
    # an account with no breakdown rows, or a goal the provider counts no
    # leads for, produces a comparison with nothing in any list.
    segments: SegmentComparison = field(default_factory=SegmentComparison)
    # The adverts running inside this group, for the one question that
    # cannot be asked at this level: which of them earned the money.
    #
    # Empty by default, and that is the guard rather than an omission. A
    # group whose adverts were never read compares nothing, and a group
    # with one advert has no cut to make - see ``core.agent.rules.creative``.
    ads: tuple["AdFacts", ...] = ()
    # Whether a lead could ever appear against this ad set.
    #
    # **False by default, and that is the safe direction rather than a
    # convenience.** A caller that forgets loses a proposal; a caller that
    # got the other default would judge a call campaign on leads it cannot
    # produce and offer to stop a telephone that is ringing. The two
    # mistakes are not the same size.
    counts_leads: bool = False
    # What one result is for this group - see :func:`core.metrics.outcome_of`
    # - and so the only figure it may be judged by. A conversation group is
    # doing well or badly on what a conversation costs, never on how many
    # people clicked it.
    #
    # ``"none"`` by default, for the reason ``counts_leads`` above is False:
    # a group whose result nobody can count is one to form no opinion about.
    # A lead group reads ``counts_leads`` first, so the two cannot disagree
    # about which family it belongs to - see
    # :func:`core.agent.benchmark.family_of`.
    outcome: Outcome = "none"
    # Whether this product built the campaign this group sits under.
    #
    # A connected cabinet inherits whatever was already running on the ad
    # account, and most of that was made in Ads Manager by somebody who is
    # not this product - an agency, a media buyer, the owner two years ago.
    # Those campaigns are the owner's advertising and their figures are
    # read like any other, but what may be *done* to them is narrower: a
    # stop and a budget, never the audience. Somebody built that audience
    # deliberately, in a console this product cannot see the reasoning of,
    # and replacing it is not a decision to offer on the strength of a
    # week of figures.
    #
    # **False by default, and that is the safe direction rather than a
    # convenience.** A caller that forgets loses a proposal - a feature
    # that quietly does not appear. The other default rewrites a
    # stranger's targeting.
    is_ours: bool = False
    # What the provider says is wrong with this group right now, in its own
    # numbers.
    #
    # **Opaque here, and that is the whole of their design.** A code means
    # nothing to arithmetic, and a rule that branched on one would be a
    # rule about Meta rather than about advertising. What they buy is a
    # boolean - the provider has something to say about this group - plus a
    # list to store beside the proposal, so the sentence a reader sees can
    # be rebuilt from the row months later.
    #
    # Current state rather than history, like the column they are read
    # from: a fault is present now or cleared, never dated.
    issue_codes: tuple[str, ...] = ()
    # The advertiser's own saved audiences this group is aimed at that the
    # provider will no longer deliver to - deleted, withdrawn, or blocked.
    #
    # Answered by the caller, because it is a join: the spec names ids and
    # only the mirror of the account's audiences knows which of them the
    # platform still accepts. The rule that reads this proposes taking
    # them out - see :mod:`core.agent.repair`, which also says why only
    # one side of the spec may be edited.
    unusable_audience_ids: tuple[str, ...] = ()
    # What the provider suggests could be better here. Meanings, not its
    # own codes - see :data:`core.agent.contracts.ProviderAdvice`.
    advice: tuple[ProviderAdvice, ...] = ()
    # The window one count per step, and what a click lands on - the two
    # things the diagnosis reads that no rule above does. See
    # :mod:`core.agent.funnel`.
    funnel: Funnel = field(default_factory=Funnel)
    landing: Landing = field(default_factory=Landing)
    # Every cut of this group's money the nightly sync keeps, by kind -
    # placement, region, age and gender - biggest spender first. Raw
    # figures rather than a comparison: ``segments`` above compares on
    # leads, and the diagnosis asks which slice is dear to *show*.
    slices: Mapping[str, tuple[SegmentFigures, ...]] = field(default_factory=dict)

    @property
    def budgeted_minor(self) -> int:
        """What this ad set was allowed to spend over the window.

        Zero when it holds no budget of its own, which is what makes every
        share computed from it fall to zero rather than divide.
        """
        if not self.daily_budget_minor or self.days_with_spend <= 0:
            return 0
        return self.daily_budget_minor * self.days_with_spend

    @property
    def spend_share(self) -> int:
        """How much of its allowance it actually used, as a percentage.

        The figure that separates "this is not working" from "this is not
        being shown". An ad set at a hundred is constrained by its budget
        and would spend more if it had it; one at forty cannot find enough
        people to show the ad to, and giving it more money changes nothing.
        """
        allowance = self.budgeted_minor
        if allowance <= 0:
            return 0
        return round(self.totals.spend_minor / allowance * 100)


@dataclass(frozen=True, slots=True)
class AccountFacts:
    """The window, and every ad set in it.

    The account totals are the benchmark. Every comparison a rule makes is
    against this account's own history rather than against a number written
    into the code: a barbershop and a clinic do not share a cost per lead,
    and the only honest reference for "expensive" is what the same owner
    normally pays.
    """

    provider: ProviderName
    currency: str
    window_days: int
    totals: Totals
    adsets: tuple[AdSetFacts, ...] = ()
    # The same sums over the ad sets that can produce a lead, and the only
    # figure the cost rules are allowed to measure against.
    #
    # **Apart from ``totals``, because they answer different questions.**
    # "What did this account spend" includes the call campaign and the
    # website campaign; "what does a lead cost here" cannot, because they
    # add spend to that division and nothing to the other side of it. One
    # website campaign beside one lead campaign doubles the apparent price
    # of a lead - which lifts the waste threshold past the ad sets it was
    # written to catch and makes every remaining lead ad set look cheaper
    # than it is.
    #
    # Empty by default, which switches every cost rule off rather than
    # letting one run against a benchmark nobody supplied. The same
    # direction ``counts_leads`` takes above.
    lead_totals: Totals = field(default_factory=Totals)
    # The pictures the account holds itself, newest first. What a fix for an
    # advert whose picture the provider cannot show is chosen from - and
    # the only pictures one can be: a creative naming another account's
    # picture is accepted and fails once it delivers.
    library: tuple[LibraryImage, ...] = ()

    def in_campaign(self, campaign_external_id: str) -> tuple[AdSetFacts, ...]:
        """Every ad set under one campaign, whatever its state."""
        return tuple(
            item
            for item in self.adsets
            if item.campaign_external_id == campaign_external_id
        )

    def only_ours(self) -> "AccountFacts":
        """The same account with the campaigns built elsewhere removed.

        What a rule declaring ``our_campaigns_only`` is handed - see
        :data:`core.agent.rules.RULES`. Narrowing the account rather than
        adding a condition inside five rules is the mechanism
        :meth:`only_lead_goals` already established: a rule cannot skip a
        check it is never shown the subject of.

        ``totals`` is carried through untouched, like above. A rule that
        reports what the account spent should report what the account
        spent.
        """
        return replace(self, adsets=tuple(item for item in self.adsets if item.is_ours))

    def only_lead_goals(self) -> "AccountFacts":
        """The same account with the ad sets that cannot bring a lead removed.

        What a rule declaring ``needs_leads`` is actually handed - see
        :data:`core.agent.rules.RULES`. Narrowing the *account* rather than
        adding a condition inside each rule is what makes this impossible
        to forget: a rule cannot skip a check it is never shown the subject
        of, and a rule added next year states which kind it wants at the
        moment it is registered.

        ``totals`` is carried through untouched. A rule that reports what
        the account spent should report what the account spent, and the
        benchmark it compares against is a separate field for exactly that
        reason.
        """
        return replace(
            self, adsets=tuple(item for item in self.adsets if item.counts_leads)
        )


def troubled(item: AdSetFacts) -> bool:
    """Whether the provider has stopped this group over a fault of its own.

    **The one exception to :func:`judgeable`, and it had to be one.** Every
    other rule in this package refuses to look at an ad set that is not
    delivering, which is right for all of them and exactly wrong here: a
    group the provider switched off is the one case where the product has
    something urgent to say.

    None of the three conditions ``judgeable`` asks is asked here, and each
    absence has the same cause - a fault is not a measurement:

    * *Running.* It is not, and that is the subject.
    * *Not learning.* A group that is not being delivered is not learning
      who to deliver it to. There is no learning left here to protect.
    * *Enough days with spend.* A fault needs no window. It is either
      reported or it is not.
    """
    return (
        bool(item.issue_codes) and item.delivery != _ACTIVE and not switched_off(item)
    )


def switched_off(item: AdSetFacts) -> bool:
    """Whether the owner, or a campaign above it, has this group switched off.

    Not the provider's doing, so nothing here is something to fix: a
    proposal about it would ask the owner to repair what they put away.
    """
    return item.delivery in _SWITCHED_OFF


def judgeable(item: AdSetFacts, policy: Policy) -> bool:
    """Whether this ad set has earned an opinion yet.

    The one condition every rule in this package shares. Three things have
    to be true: it is running, the provider is not still learning who to
    show it to, and it has spent on enough days to have said anything.

    Learning ad sets are excluded from **every** rule, not only from the
    ones that would edit a budget. An ad set in its learning phase has no
    leads *because* it is learning, and a product that read that as
    failure would stop every campaign three days after starting it.
    """
    return (
        item.delivery == _ACTIVE
        and not item.is_learning
        and item.days_with_spend >= policy.min_days
    )


__all__ = [
    "AccountFacts",
    "AdFacts",
    "AdSetFacts",
    "Half",
    "LibraryImage",
    "ctr_bp",
    "judgeable",
    "switched_off",
    "troubled",
]
