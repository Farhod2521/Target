"""Which preparation step an account is on, and what is still in its way."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

StepId = Literal[
    "profile", "connect", "ad_account", "page", "leads", "pixel", "telegram"
]

StepState = Literal["done", "current", "attention", "waiting", "optional"]

ORDER: tuple[StepId, ...] = ("connect", "page", "ad_account", "profile", "leads")

PAIRED: tuple[StepId, StepId] = ("page", "ad_account")

GATES: tuple[StepId, ...] = ("connect", "page", "ad_account", "profile")

FINISH_GATES: tuple[StepId, ...] = ("connect", "page", "ad_account")


@dataclass(frozen=True, slots=True)
class SetupFacts:
    """Everything the plan is decided from, gathered once by the caller."""

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
    telegram_offered: bool = False
    telegram_linked: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    """One row of the preparation screen."""

    id: StepId
    state: StepState
    optional: bool = False


def _profile_done(facts: SetupFacts) -> bool:
    """The category counts as much as the name."""
    return facts.has_profile and facts.has_category


def _connect_done(facts: SetupFacts) -> bool:
    """Connected, and carrying what it was connected for."""
    return facts.connected and not facts.scopes_missing


def _ad_account_done(facts: SetupFacts) -> bool:
    return facts.ad_account_chosen


def _page_done(facts: SetupFacts) -> bool:
    return facts.page_chosen


def _leads_done(facts: SetupFacts) -> bool:
    """Subscribed, and not refused over an agreement nobody has given."""
    return facts.leads_subscribed and facts.page_terms_accepted is not False


_DONE: dict[StepId, Callable[[SetupFacts], bool]] = {
    "profile": _profile_done,
    "connect": _connect_done,
    "ad_account": _ad_account_done,
    "page": _page_done,
    "leads": _leads_done,
}

_ATTENTION: dict[StepId, Callable[[SetupFacts], bool]] = {
    "connect": lambda facts: facts.connected and facts.scopes_missing,
    "ad_account": lambda facts: facts.connected and facts.ad_accounts_found == 0,
    "page": lambda facts: facts.connected and facts.pages_found == 0,
    "leads": lambda facts: facts.page_terms_accepted is False,
}


def plan(facts: SetupFacts) -> tuple[Step, ...]:
    """The five steps and the optional sixth, each in one state."""
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
    """The phone, asked for last and never in the way of anything."""
    if facts.telegram_linked:
        return Step(id="telegram", state="done")
    if all(step.state == "done" for step in before):
        return Step(id="telegram", state="current")
    return Step(id="telegram", state="optional")


def _pixel_step(facts: SetupFacts) -> Step:
    """The one step that is never anybody's next thing to do."""
    if facts.pixel_chosen:
        return Step(id="pixel", state="done", optional=True)
    if facts.ad_account_chosen:
        return Step(id="pixel", state="optional", optional=True)
    return Step(id="pixel", state="waiting", optional=True)


def paired_state(steps: tuple[Step, ...]) -> StepState:
    """The state of the one row the ``PAIRED`` steps are drawn as."""
    by_id = {step.id: step.state for step in steps}
    page, account = PAIRED
    if by_id[page] != "done":
        return by_id[page]
    return by_id[account]


def is_ready(facts: SetupFacts) -> bool:
    """Whether a campaign can be created at all."""
    return all(_DONE[step_id](facts) for step_id in GATES)


def can_finish(facts: SetupFacts) -> bool:
    """Whether preparation may be closed."""
    return all(_DONE[step_id](facts) for step_id in FINISH_GATES)


def blocking(facts: SetupFacts) -> StepId | Literal[""]:
    """The step the create button would be refused on, or ``""``."""
    for step_id in GATES:
        if not _DONE[step_id](facts):
            return step_id
    return ""


def progress(facts: SetupFacts) -> tuple[int, int]:
    """How many of the steps are finished, and out of how many."""
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
