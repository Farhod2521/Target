"""The seven strategies, and the one function that asks them all.

The product's own playbook, the list CLAUDE.md was written around: wide
start, broad delivery, lookalike, retargeting, a goal that fits the
business, creative testing, slow scaling. Every one of them is technically
possible; this module is where "possible" becomes "next".

The shape is the rules', deliberately - a registry of pure functions a
reader can walk - but the nature is not. A rule is reactive: it looks at
one ad set's week and says *something is wrong here*. A strategy is
planned: it looks at the whole account's standing and says *this is what
comes next*. Rules rank by money at stake; strategies have no stake to
rank by, so the registry order **is** the reading order, foundation
first - and unlike the rules' table, that order is meaning, not
convention.

Nothing here proposes an executable change. Advice becomes a card, and
what ``advise`` returns is stable codes, derived from one state,
replayable from the numbers stored beside them.
"""

from dataclasses import dataclass
from typing import Final, Protocol

from core.strategy.advice import (
    NEED_SEED_AUDIENCE,
    NEED_TRAFFIC_SOURCE,
    StrategyAdvice,
)
from core.strategy.lifecycle import may_adjust
from core.strategy.maturity import (
    DEFAULT_THRESHOLDS,
    AccountMaturity,
    MaturityThresholds,
    maturity,
)
from core.strategy.state import StrategyState

# Stable codes, one per strategy. The Django layer maps them to Uzbek and
# later blocks store them, so renaming one is a migration, not a rename.
CHOOSE_GOAL = "choose_goal"
WARM_START = "warm_start"
GO_BROAD = "go_broad"
BUILD_LOOKALIKE = "build_lookalike"
RETARGET = "retarget"
CREATIVE_TEST = "creative_test"
SCALE_UP = "scale_up"

# The one delivery state a strategy counts, spelled as the domain spells
# it - the same private declaration ``core.agent.guardrails`` makes, for
# the same reason: everything else in a delivery column describes what the
# provider decided, not what is running.
_ACTIVE: Final = "active"


class StrategyFn(Protocol):
    """What every strategy looks like from the outside."""

    def __call__(
        self, *, state: StrategyState, maturity: AccountMaturity
    ) -> StrategyAdvice | None: ...


@dataclass(frozen=True, slots=True)
class Strategy:
    """One strategy, and the code it answers under."""

    code: str
    run: StrategyFn


def choose_goal(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """Nothing is running - the next step is a campaign, whatever else is true.

    The fifth strategy, in its honest domain form. *Which* goal fits the
    business is answered where goals are offered - the launch flow, per
    category - and no arithmetic here could answer it better. What the
    playbook knows is the loudest fact an account has: zero delivering
    campaigns means every other card is theory.
    """
    if state.active_campaigns > 0:
        return None
    return StrategyAdvice(
        strategy=CHOOSE_GOAL,
        evidence={"active_campaigns": 0},
    )


def warm_start(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """A new account should aim wide: one or two interests, nothing clever.

    The first strategy. The provider has nothing to optimise on yet, and
    every narrowing multiplies a guess - so the next campaign's shape is
    the advice, not any change to a running one. Fires on maturity alone:
    it holds whether the account is empty or already running its first
    narrow campaign, because it is about what the account *knows*, which
    is nothing yet.
    """
    if maturity != "new":
        return None
    return StrategyAdvice(
        strategy=WARM_START,
        evidence={
            "window_days": state.history.window_days,
            "reported_results": state.history.reported_results,
        },
    )


def go_broad(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """A proven account still narrowing by interest is leaving reach unused.

    The second strategy. Only for ad sets whose stored choice *is*
    interests: a hand-built ad set has no stored mode, and "switch to
    broad" said about a choice nobody recorded would be speaking with a
    confidence the data does not have - ``None`` means unknown, never
    "interests". Which of broad and automatic to prefer is a sentence for
    the screen; the direction is the advice.
    """
    if maturity != "proven":
        return None
    narrowed = sum(
        1
        for item in state.adsets
        if item.delivery == _ACTIVE and item.mode == "interests"
    )
    if narrowed == 0:
        return None
    return StrategyAdvice(
        strategy=GO_BROAD,
        evidence={"interest_adsets": narrowed},
    )


def build_lookalike(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """A customer base is the one asset the provider cannot find alone.

    The third strategy, and the one place advice fires regardless of
    maturity: a business day one on this platform can hold years of
    customers, and a usable seed makes the lookalike the next step
    whatever the account has learned. With no seed the advice inverts -
    *bring the list* - but not for a new account, whose next step is a
    warm start, not upload plumbing. One lookalike already built closes
    the subject; refreshing an ageing one is a separate question.
    """
    if state.assets.lookalikes > 0:
        return None
    if state.assets.ready_seeds > 0:
        return StrategyAdvice(
            strategy=BUILD_LOOKALIKE,
            evidence={"ready_seeds": state.assets.ready_seeds},
        )
    if maturity == "new":
        return None
    return StrategyAdvice(
        strategy=BUILD_LOOKALIKE,
        ready=False,
        needs=(NEED_SEED_AUDIENCE,),
        evidence={"ready_seeds": 0},
    )


def retarget(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """People who already came are the cheapest people to bring back.

    The fourth strategy, shaped exactly as the third: an existing
    retargeting audience closes the subject - including one somebody built
    in the provider's console, which gathers just as well - a usable
    source makes it ready, and a missing source becomes the advice itself,
    except on a new account, where traffic worth recapturing does not
    exist yet.
    """
    if state.assets.retargeting > 0:
        return None
    if state.assets.has_traffic_source:
        return StrategyAdvice(strategy=RETARGET)
    if maturity == "new":
        return None
    return StrategyAdvice(
        strategy=RETARGET,
        ready=False,
        needs=(NEED_TRAFFIC_SOURCE,),
    )


def creative_test(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """One ad in an ad set is a campaign with no comparison running.

    The sixth strategy's first half - putting variants up; which one to
    keep is the comparison screen's job. Counted only where a change may
    land: an ad set in its test
    window or still learning gets its variants when it is older, because
    adding a creative resets the very learning being waited out.
    """
    alone = sum(
        1
        for item in state.adsets
        if item.delivery == _ACTIVE and may_adjust(item.stage) and item.creatives == 1
    )
    if alone == 0:
        return None
    return StrategyAdvice(
        strategy=CREATIVE_TEST,
        evidence={"single_creative_adsets": alone},
    )


def scale_up(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """Something here has earned more money, slowly.

    The seventh strategy. An ad set reaches its scaling stage on the
    provider's own SUCCESS verdict plus real evidence days - see
    ``lifecycle`` - and that is the only footing on which "spend more" is
    a plan rather than a bet. How much more and how often is bounded
    elsewhere: the budget step and the stage's longer cooldown.
    """
    proven = sum(
        1
        for item in state.adsets
        if item.delivery == _ACTIVE and item.stage == "scaling"
    )
    if proven == 0:
        return None
    return StrategyAdvice(
        strategy=SCALE_UP,
        evidence={"scaling_adsets": proven},
    )


# The playbook, in reading order: what to run, how to aim it, what to
# build beside it, how to grow it. Foundation first - the order is the
# meaning, which is the one way this table differs from the rules'.
STRATEGIES: tuple[Strategy, ...] = (
    Strategy(code=CHOOSE_GOAL, run=choose_goal),
    Strategy(code=WARM_START, run=warm_start),
    Strategy(code=GO_BROAD, run=go_broad),
    Strategy(code=BUILD_LOOKALIKE, run=build_lookalike),
    Strategy(code=RETARGET, run=retarget),
    Strategy(code=CREATIVE_TEST, run=creative_test),
    Strategy(code=SCALE_UP, run=scale_up),
)

# Every strategy code, for the Django layer to map to sentences and for a
# test to pin. Derived rather than written out, the ``CODES`` bargain.
STRATEGY_CODES: tuple[str, ...] = tuple(item.code for item in STRATEGIES)


def advise(
    *,
    state: StrategyState,
    thresholds: MaturityThresholds = DEFAULT_THRESHOLDS,
) -> list[StrategyAdvice]:
    """Every direction this account should hear about, in reading order.

    Maturity is derived here, once, and every strategy sees the same
    answer - a caller cannot hand one strategy a different account than
    the next. At most one advice per strategy, by construction: each
    returns a value or nothing, and nothing is dropped or capped here.
    How many cards a screen shows is that screen's decision.
    """
    standing = maturity(history=state.history, thresholds=thresholds)
    found: list[StrategyAdvice] = []
    for entry in STRATEGIES:
        item = entry.run(state=state, maturity=standing)
        if item is not None:
            found.append(item)
    return found


# The strategy functions are reachable through the registry and are not
# public: run alone, one skips the shared maturity ``advise`` derives.
__all__ = [
    "BUILD_LOOKALIKE",
    "CHOOSE_GOAL",
    "CREATIVE_TEST",
    "GO_BROAD",
    "RETARGET",
    "SCALE_UP",
    "STRATEGIES",
    "STRATEGY_CODES",
    "WARM_START",
    "Strategy",
    "StrategyFn",
    "advise",
]
