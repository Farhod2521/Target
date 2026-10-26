"""What the agent proposes, and whether it is allowed to.

These are domain values, not wire formats: nothing parses them from JSON, so
they are dataclasses rather than pydantic models. The provider-facing DTOs
live in ``adskit`` and are a different thing entirely.

**The agent proposes; the owner decides.** Every kind below reaches a
provider only after somebody pressed a button, which is a product decision
and not a limitation waiting to be lifted. It shapes this file: a finding
carries the evidence it was made from, because a proposal read a day later
has to be re-checkable against the account as it is *then*, and a change
that made sense on Tuesday's numbers is not a change to make on Thursday's.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from adskit import ExternalRef, Level

from core.metrics import Totals

# A closed set. What the agent may propose is the list of things this
# product knows how to explain, carry out and undo - keeping it a Literal
# means adding a new one is a visible, reviewable change rather than a new
# string appearing in a database column.
SuggestionKind = Literal[
    "pause",
    "resume",
    "increase_budget",
    "decrease_budget",
    "swap_targeting",
    # The same write as the one above and deliberately not the same kind.
    # Both replace an audience; they promise opposite things - one that
    # delivery opens up, one that a dead slice stops costing money - and a
    # single kind would put one label above both and grade them by one
    # test. What the screen says and what the assessment measures are both
    # read off this word.
    "narrow_targeting",
    # The third write to the same field and the third promise on it.
    # ``swap_targeting`` says delivery will open up, ``narrow_targeting``
    # that a dead slice will stop costing money, and this one that an
    # advert the provider switched off will run again. Somebody reading a
    # button deserves to be told which of the three they are pressing -
    # which is the whole reason this set is spelled out rather than
    # collapsed into one "edit the audience".
    "drop_audience",
    # The one kind that is not carried out by pressing a button. A new
    # advert is words somebody reads before they are published, so this is
    # answered in a dialog that shows them - and only saving that dialog
    # carries it out. See ``apps.agent.services.approve_suggestion``.
    "new_ad",
    # The same write as ``new_ad`` with nothing to read first: the words
    # stay, and the picture the provider can no longer show is replaced by
    # one the account holds. The card shows which, so one press carries it
    # out.
    "new_picture",
]

# What the provider itself suggests changing about an object, as meanings
# rather than as the provider's own numbers.
#
# **A closed set of meanings, and the translation happens outside this
# package.** Meta leaves a recommendation on an ad set as a code, a title
# and a paragraph of English, and it adds new ones without telling anybody.
# A rule that read those would be a rule about Meta, and a rule that
# guessed at an unfamiliar code would propose a change to somebody's live
# account on the strength of a number it had never seen. So the Django
# layer maps the ones it recognises onto this list - see
# ``apps.ads.recommendations`` - and everything else reaches the owner as
# what the provider said, on the waiting list, with no button on it.
ProviderAdvice = Literal[
    # "Let the platform show this beyond the audience you named." The one
    # recommendation this product can carry out today, because it is a
    # write to the targeting spec and nothing else.
    "broader_audience",
]


@dataclass(frozen=True, slots=True)
class Policy:
    """The thresholds one owner's decisions are made against.

    Defaults, not settings: an account that never opens the settings page
    still gets sensible behaviour, and every field here is a number
    somebody could reasonably want to move.

    The two share figures are percentages *of this account's own* cost per
    lead. Nothing in this file is an absolute amount of money,
    because a barbershop and a clinic do not share a cost per lead and the
    only honest reference for "expensive" is what the same owner normally
    pays.
    """

    # How much history one decision is made on. A week: long enough that a
    # quiet Sunday does not read as a failure, short enough that a campaign
    # which broke on Monday is not defended by the Friday before it.
    window_days: int = 7
    # How far back "what this pair usually does" is read: two weeks, so a
    # median day has a week either side of it - see ``core.agent.usual``.
    usual_days: int = 14
    # Nothing younger than this is judged at all. An ad set on its second
    # day has no history, and every rule here would be reading noise.
    min_days: int = 3
    # How long the same object is left alone after anything touched it.
    # Two days rather than one: a budget change needs a full day to show
    # up in the figures, and a decision made on the day of a change is a
    # decision made on the state before it. A floor, not the whole answer:
    # an ad set in its scaling stage waits longer - see
    # ``core.strategy.lifecycle.cooldown_hours``, which takes this as its
    # lower bound.
    cooldown_hours: int = 48
    # How old an object must be before anything at all is judged about it.
    # Age, not evidence: ``min_days`` counts days that actually spent, and
    # this counts hours since the thing started existing. An ad set
    # created six days ago that spent on two of them is past this and
    # still short of ``min_days`` - the two checks answer different
    # questions and both stand. Three days of astronomical time, because
    # a fresh object's numbers are noise whatever they say.
    test_hours: int = 72
    # How many proposals one night may produce. A screen with fifteen
    # things to approve is a screen nobody approves anything on.
    max_per_run: int = 3
    # How long a proposal the owner said no to stays un-repeated, for the
    # same rule against the same object. A week, and openly a heuristic:
    # long enough that "no" is heard, short enough that a campaign whose
    # numbers keep worsening gets asked about again. "The figures moved
    # enough to ask sooner" would be the sharper trigger, and defining
    # "enough" per rule is a separate question, not this field's.
    rejected_quiet_days: int = 7
    # How far a budget moves in one step, as a percentage. Twenty rather
    # than twenty-five: under the provider's own "significant edit" line
    # as commonly held, and small enough that two steps in the wrong
    # direction are recoverable.
    budget_step_pct: int = 20
    # A cost per lead at or below this share of the account's is worth more
    # money. Its opposite, "dearer", is not a policy figure: it is the
    # brief's, one line for every rule - see ``core.agent.usual.price_level``
    # - and so is "spent enough to tell", see ``core.agent.sufficiency``.
    win_share_pct: int = 70
    # An ad set using at least this much of its allowance is held back by
    # its budget and would spend more. Below the second figure it cannot
    # find people to show the ad to, and money is not what it is short of.
    constrained_share_pct: int = 90
    starved_share_pct: int = 60
    # How far the link click-through rate must fall between the first half
    # of the window and the second before the audience counts as worn out.
    #
    # **Approximate, and openly so.** The provider publishes no threshold
    # for any of this - its own reference defines frequency and says
    # nothing about what a high one is - so a figure copied from advice
    # elsewhere would be a number with a source rather than a reason. A
    # third is large enough that it is not the ordinary week-to-week
    # wobble of a small account, and it is a percentage of the ad set's
    # own earlier rate rather than an absolute, which is the same bargain
    # every other share here makes.
    ctr_drop_pct: int = 30
    # How much of one ad set's money a dead slice of its audience must be
    # taking before cutting the slice is worth restarting delivery for.
    #
    # Also approximate. The lower it goes the more often an ad set has its
    # learning thrown away to save a rounding error; from the other side, a
    # slice at two percent of the money is not worth an edit, and one at
    # forty is the whole problem.
    dead_segment_share_pct: int = 20


@dataclass(frozen=True, slots=True)
class Finding:
    """One change worth proposing, with the arithmetic that produced it.

    ``rule`` is a stable code and the reason this is not merely a
    suggestion with a sentence attached: the same rule is run again when
    somebody approves, against the account as it is at that moment, and a
    finding that no longer appears is a proposal that has expired rather
    than one to carry out.

    ``evidence`` is what the explanation is written from and what the
    screen shows under "why". Numbers only - no sentence is built in this
    package, which has no language.
    """

    kind: SuggestionKind
    rule: str
    ref: ExternalRef
    # The object one level up, when this one sits inside another. Empty
    # where the finding is about the whole thing.
    #
    # What it buys is one invariant: **a change to a part is withdrawn when
    # the whole is being changed.** "Stop this group" and "stop one advert
    # inside this group" are both sound on their own and incoherent on one
    # screen, and they would both survive the one-finding-per-object rule -
    # an advert and its group are different ids. See :func:`core.agent.
    # rules.scan`, which is where the withdrawal happens.
    parent_id: str = ""
    # Money at stake, in minor units. Used only to rank findings when a run
    # produces more than it is allowed to propose: the change about the
    # most money is the one worth somebody's attention first.
    weight: int = 0
    evidence: Mapping[str, Any] = field(default_factory=dict)
    # What the write needs, in provider shape. Empty for a stop or a start,
    # where the kind is the whole instruction.
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> Level:
        """Which layer of the account this aims at."""
        return self.ref.level


@dataclass(frozen=True, slots=True)
class Aftermath:
    """The days since a change, in the counts a verdict is read from.

    A value of its own rather than a bare :class:`~core.metrics.Totals`,
    because two of the three things a verdict needs are not totals:
    ``days`` decides whether there is enough of an aftermath to judge at
    all, and ``link_clicks`` is the figure one rule was triggered by and
    must therefore be graded on - ``Totals`` counts every click on the
    unit, caption expansions included.
    """

    totals: Totals = field(default_factory=Totals)
    link_clicks: int = 0
    days: int = 0


@dataclass(frozen=True, slots=True)
class Verdict:
    """How one change turned out, with the numbers that say so.

    ``figures`` is the aftermath as it was read - stored beside the verdict
    so the comparison can be re-checked against ``evidence`` months later,
    the same replayability every suggestion has.
    """

    outcome: str
    figures: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    """Whether a suggestion may be applied, and why not when it may not.

    ``reason`` is filled in on refusal, and it is a **code** rather than a
    sentence - one of ``core.agent.guardrails``' ``REFUSED_*`` constants,
    which the Django layer turns into Uzbek. It has to reach the user
    somehow: an agent that silently does nothing is indistinguishable from
    a broken one. It cannot reach them from here, because a sentence
    written in this package can be neither translated nor logged.
    """

    allowed: bool
    reason: str
