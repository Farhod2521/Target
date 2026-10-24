"""Which preparation step an account is on, and what is still in its way.

Without one sequence, each screen knows one precondition and nothing knows
the order: an owner finishes both steps the dashboard lists, presses the
only button on the page, answers four questions, waits a minute for a
proposal to be written - and is told at the end of it to go and choose a
page nothing had ever mentioned.

The page comes before the profile, because the profile is one page's
description and there is nothing to describe until one has been chosen.

So the order is written down once, here, and every screen reads it from the
same place.

**Two different questions, deliberately kept apart.** *What is next* walks
all five steps. *May a campaign be created yet* walks only the four the
provider actually refuses on. Connecting leads is what makes an enquiry
arrive in the cabinet; it is not what stops an advert being made, and a
button disabled over it would refuse somebody advertising a phone number
because of a form they are not using.

*May preparation be closed* is a third question and walks fewer still: only
what the press makes permanent. See ``FINISH_GATES``.

No sentences here, only ids. What a step is called, and in which language,
belongs to the template - a ``gettext`` call in this file would be a Django
import in ``core/``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

# The steps, in the only order they can be done in. Each one needs the one
# before it: nothing to choose without a connection, no paying account to
# name until there is a page it pays for, no business to describe until a
# page has been chosen, and no lead subscription to make until then either.
#
# A profile describes one page - one trade, one town, one set of
# opening hours - so asking for it before a page is chosen is asking
# somebody to describe a business the cabinet cannot yet name. Asked
# afterwards, the page's own address fills half the form in.
StepId = Literal[
    "profile", "connect", "ad_account", "page", "leads", "pixel", "telegram"
]

# What a step looks like on a screen.
#
# ``attention`` is ``current`` with the fix somewhere else: a permission
# withheld on Meta's consent screen, an empty list of pages, an agreement
# only a page's administrator can give. The distinction is worth a state of
# its own because it decides what the screen draws - a control to press, or
# a way out to somebody else's site.
StepState = Literal["done", "current", "attention", "waiting", "optional"]

ORDER: tuple[StepId, ...] = ("connect", "page", "ad_account", "profile", "leads")

# Two steps the screen draws as one: a page is chosen together with the
# account that pays for it, so they are counted once as well.
PAIRED: tuple[StepId, StepId] = ("page", "ad_account")

# The four a campaign cannot be created without. ``leads`` is missing on
# purpose - see the module docstring - and so is the subscription, which is
# not a step: it opens by itself at sign-up, and when it lapses every screen
# in the cabinet already says so.
#
# Same order as above, and it has to be: this is what names the step a
# blocked button points at, and a list in a different order would send
# somebody to the last thing they cannot do rather than the next one.
GATES: tuple[StepId, ...] = ("connect", "page", "ad_account", "profile")

# What the finish press fixes, and so what it waits for: the ad account and
# the page, and the connection they were read through. The profile is not
# among them. It stays editable after the press, and it is described per
# page - so a finish that waited on it would hold the one irreversible
# choice hostage to a form that choice does not touch, and an owner with
# several pages would lose the button every time they looked at a page they
# had not described yet. The profile still holds the launch button.
FINISH_GATES: tuple[StepId, ...] = ("connect", "page", "ad_account")


@dataclass(frozen=True, slots=True)
class SetupFacts:
    """Everything the plan is decided from, gathered once by the caller.

    Plain values rather than rows: this is what lets the whole sequence be
    tested without a database, a provider or a fixture, and it is why the
    ordering lives here rather than in the view that renders it.

    ``page_terms_accepted`` is three-state and that is not an accident. A
    page fetched before the product started asking holds ``None``, which
    means "Meta was never asked" - and a launch refused over a question
    nobody put costs more than the refusal saves. Only an explicit ``False``
    is a refusal.
    """

    has_profile: bool = False
    has_category: bool = False
    connected: bool = False
    scopes_missing: bool = False
    ad_account_chosen: bool = False
    ad_accounts_found: int = 0
    page_chosen: bool = False
    pages_found: int = 0
    page_terms_accepted: bool | None = None
    leads_subscribed: bool = False
    pixel_chosen: bool = False
    # Whether this deployment can send anything to a phone at all, and
    # whether this account has one listening. The first decides whether the
    # step is drawn: a deployment with no bot has nothing to ask for, and a
    # sixth step nobody could finish would make every cabinet read as
    # unfinished.
    telegram_offered: bool = False
    telegram_linked: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    """One row of the preparation screen."""

    id: StepId
    state: StepState
    optional: bool = False


def _profile_done(facts: SetupFacts) -> bool:
    """The category counts as much as the name.

    It is what selects a preset, and without it the wizard refuses at its
    first screen with ``ProfileIncomplete`` - so a profile saved without one
    is not a finished step however complete it looks.
    """
    return facts.has_profile and facts.has_category


def _connect_done(facts: SetupFacts) -> bool:
    """Connected, and carrying what it was connected for.

    A permission unticked on Meta's consent screen leaves a token that works
    for everything else, so "connected" on its own is not the answer.
    """
    return facts.connected and not facts.scopes_missing


def _ad_account_done(facts: SetupFacts) -> bool:
    return facts.ad_account_chosen


def _page_done(facts: SetupFacts) -> bool:
    return facts.page_chosen


def _leads_done(facts: SetupFacts) -> bool:
    """Subscribed, and not refused over an agreement nobody has given.

    The two are separate facts with confusingly similar names. The
    subscription decides whether a lead *arrives*; the terms decide whether
    an ad set is *created at all*. Both belong to this step because both are
    about the same page and are fixed in the same minute.
    """
    return facts.leads_subscribed and facts.page_terms_accepted is not False


_DONE: dict[StepId, Callable[[SetupFacts], bool]] = {
    "profile": _profile_done,
    "connect": _connect_done,
    "ad_account": _ad_account_done,
    "page": _page_done,
    "leads": _leads_done,
}

# Which steps can be stuck on something outside this product, and how to
# tell. A step with no entry here is never ``attention``: filling in a
# profile cannot be blocked by anybody else.
_ATTENTION: dict[StepId, Callable[[SetupFacts], bool]] = {
    # Connected, and something was withheld. Reconnecting is the fix and it
    # happens on Meta's screen, not ours.
    "connect": lambda facts: facts.connected and facts.scopes_missing,
    # Connected and there is nothing to choose. An advertiser here has to go
    # and open an ad account before this screen can do anything for them,
    # and saying "not found" without saying that is a dead end.
    "ad_account": lambda facts: facts.connected and facts.ad_accounts_found == 0,
    "page": lambda facts: facts.connected and facts.pages_found == 0,
    # Only an explicit refusal. ``None`` is "never asked" and is not a
    # problem to show anybody - see ``SetupFacts``.
    "leads": lambda facts: facts.page_terms_accepted is False,
}


def plan(facts: SetupFacts) -> tuple[Step, ...]:
    """The five steps and the optional sixth, each in one state.

    At most one of them is ``current`` or ``attention``: the first that is
    not finished. Everything unfinished after it is ``waiting``, because two
    open steps is how somebody does the second one first and meets a refusal
    nothing warned them about.

    A finished step stays finished wherever it sits. When a connection
    expires the step above reopens and the page chosen underneath it is
    still chosen - drawing that as waiting would send somebody to redo a
    choice that is still on the row.

    Finished steps stay on the screen rather than disappearing. "Did I do
    that one?" is itself a form of the confusion this module exists to end.
    """
    steps: list[Step] = []
    current_taken = False

    for step_id in ORDER:
        if _DONE[step_id](facts):
            steps.append(Step(id=step_id, state="done"))
            continue
        if current_taken:
            steps.append(Step(id=step_id, state="waiting"))
            continue
        current_taken = True
        stuck = _ATTENTION.get(step_id)
        state: StepState = (
            "attention" if stuck is not None and stuck(facts) else "current"
        )
        steps.append(Step(id=step_id, state=state))

    if facts.telegram_offered:
        steps.append(_telegram_step(facts, before=tuple(steps)))
    steps.append(_pixel_step(facts))
    return tuple(steps)


def _telegram_step(facts: SetupFacts, *, before: tuple[Step, ...]) -> Step:
    """The phone, asked for last and never in the way of anything.

    Not a gate, and it never will be: an advert is made whether or not
    anybody is told about it. But it is asked for here rather than left on a
    settings page, because a proposal the agent writes at night and an
    advert Meta refused are worth nothing to somebody who does not open the
    cabinet - and nothing else sends anybody to that page.

    ``current`` only once everything above it is done, so the screen keeps
    its one "you are here". Until then it is ``optional``: linking a phone
    depends on nothing above it, so its button works at any moment, but it
    is not the next thing to do.
    """
    if facts.telegram_linked:
        return Step(id="telegram", state="done")
    if all(step.state == "done" for step in before):
        return Step(id="telegram", state="current")
    return Step(id="telegram", state="optional")


def _pixel_step(facts: SetupFacts) -> Step:
    """The one step that is never anybody's next thing to do.

    About half the businesses here sell through Instagram and a phone
    number, and for them there is no website for a pixel to sit on. So it is
    never ``current``: an optional step drawn as the next action is a step
    people do because the screen told them to.

    ``waiting`` until an ad account is chosen, because a pixel belongs to an
    account and before that there is nothing to list.
    """
    if facts.pixel_chosen:
        return Step(id="pixel", state="done", optional=True)
    if facts.ad_account_chosen:
        return Step(id="pixel", state="optional", optional=True)
    return Step(id="pixel", state="waiting", optional=True)


def paired_state(steps: tuple[Step, ...]) -> StepState:
    """The state of the one row the ``PAIRED`` steps are drawn as.

    The page's state until a page is chosen, then the account's: the row
    is finished only when both are.
    """
    by_id = {step.id: step.state for step in steps}
    page, account = PAIRED
    if by_id[page] != "done":
        return by_id[page]
    return by_id[account]


def is_ready(facts: SetupFacts) -> bool:
    """Whether a campaign can be created at all.

    The four gates, not the five steps. See the module docstring for why
    connecting leads is not one of them.
    """
    return all(_DONE[step_id](facts) for step_id in GATES)


def can_finish(facts: SetupFacts) -> bool:
    """Whether preparation may be closed.

    The three finish gates, not the four launch gates. See ``FINISH_GATES``
    for why the profile is not one of them. They are a prefix of ``GATES``,
    so while this is ``False`` :func:`blocking` already names the step the
    finish button is waiting on.
    """
    return all(_DONE[step_id](facts) for step_id in FINISH_GATES)


def blocking(facts: SetupFacts) -> StepId | Literal[""]:
    """The step the create button would be refused on, or ``""``.

    One id, not a list. Somebody about to be told they cannot advertise yet
    needs the next thing to do, and a screen listing three of them is a
    screen that reads as further away than it is.
    """
    for step_id in GATES:
        if not _DONE[step_id](facts):
            return step_id
    return ""


def progress(facts: SetupFacts) -> tuple[int, int]:
    """How many of the steps are finished, and out of how many.

    Counted over ``ORDER`` rather than ``GATES``, so the figure on the
    screen matches the rows underneath it - with the ``PAIRED`` two counted
    once, and finished only when both are. The button can therefore be live
    at three out of four - which is correct, and is why the screen says
    something about leads there rather than simply counting.

    The phone is not counted. It is drawn under the steps as something
    extra rather than as a numbered row, and nothing waits on it.
    """
    page, account = PAIRED
    counted = tuple(step_id for step_id in ORDER if step_id != account)
    done = sum(
        _DONE[step_id](facts) and (step_id != page or _DONE[account](facts))
        for step_id in counted
    )
    total = len(counted)
    return done, total


__all__ = [
    "FINISH_GATES",
    "GATES",
    "ORDER",
    "PAIRED",
    "SetupFacts",
    "Step",
    "StepId",
    "StepState",
    "blocking",
    "can_finish",
    "is_ready",
    "paired_state",
    "plan",
    "progress",
]
