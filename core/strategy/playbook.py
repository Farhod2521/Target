"""The seven strategies, and the one function that asks them all."""

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

CHOOSE_GOAL = "choose_goal"
WARM_START = "warm_start"
GO_BROAD = "go_broad"
BUILD_LOOKALIKE = "build_lookalike"
RETARGET = "retarget"
CREATIVE_TEST = "creative_test"
SCALE_UP = "scale_up"

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
    """Nothing is running - the next step is a campaign, whatever else is true."""
    if state.active_campaigns > 0:
        return None
    return StrategyAdvice(
        strategy=CHOOSE_GOAL,
        evidence={"active_campaigns": 0},
    )


def warm_start(
    *, state: StrategyState, maturity: AccountMaturity
) -> StrategyAdvice | None:
    """A new account should aim wide: one or two interests, nothing clever."""
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
    """A proven account still narrowing by interest is leaving reach unused."""
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
    """A customer base is the one asset the provider cannot find alone."""
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
    """People who already came are the cheapest people to bring back."""
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
    """One ad in an ad set is a campaign with no comparison running."""
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
    """Something here has earned more money, slowly."""
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


STRATEGIES: tuple[Strategy, ...] = (
    Strategy(code=CHOOSE_GOAL, run=choose_goal),
    Strategy(code=WARM_START, run=warm_start),
    Strategy(code=GO_BROAD, run=go_broad),
    Strategy(code=BUILD_LOOKALIKE, run=build_lookalike),
    Strategy(code=RETARGET, run=retarget),
    Strategy(code=CREATIVE_TEST, run=creative_test),
    Strategy(code=SCALE_UP, run=scale_up),
)

STRATEGY_CODES: tuple[str, ...] = tuple(item.code for item in STRATEGIES)


def advise(
    *,
    state: StrategyState,
    thresholds: MaturityThresholds = DEFAULT_THRESHOLDS,
) -> list[StrategyAdvice]:
    """Every direction this account should hear about, in reading order."""
    standing = maturity(history=state.history, thresholds=thresholds)
    found: list[StrategyAdvice] = []
    for entry in STRATEGIES:
        item = entry.run(state=state, maturity=standing)
        if item is not None:
            found.append(item)
    return found


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
