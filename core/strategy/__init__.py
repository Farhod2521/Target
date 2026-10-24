"""The planning layer: what this account should do next.

The third vocabulary of the domain. A *preset* is a recipe - one category
and one goal, rendered to a spec. A *rule* is
reactive - one ad set's week, judged, becoming a button. A *strategy* is
planned - the whole account's standing, read, becoming a direction. The
three never blur: a strategy proposes no executable change and a rule
consults no plan, and the day either stops being true this package has
leaked.

Everything here is arithmetic over values somebody else assembled - no
Django, no clock, no provider - and every threshold either comes from the
provider's own verdict or says out loud that it is approximate. See
``maturity`` for that split; it is the whole epistemology of the package.
"""

from core.strategy.advice import (
    NEED_SEED_AUDIENCE,
    NEED_TRAFFIC_SOURCE,
    NEEDS,
    StrategyAdvice,
)
from core.strategy.lifecycle import (
    OPTIMIZING_COOLDOWN_HOURS,
    SCALING_COOLDOWN_HOURS,
    LifecycleStage,
    cooldown_hours,
    may_adjust,
    may_scale,
    stage,
)
from core.strategy.maturity import (
    DEFAULT_THRESHOLDS,
    LEARNING_SUCCESS,
    SIGNAL_WINDOW_DAYS,
    AccountMaturity,
    MaturityThresholds,
    SignalHistory,
    has_exited_learning,
    maturity,
)
from core.strategy.playbook import (
    BUILD_LOOKALIKE,
    CHOOSE_GOAL,
    CREATIVE_TEST,
    GO_BROAD,
    RETARGET,
    SCALE_UP,
    STRATEGIES,
    STRATEGY_CODES,
    WARM_START,
    Strategy,
    StrategyFn,
    advise,
)
from core.strategy.state import AdSetPosture, AudienceAssets, StrategyState

__all__ = [
    "BUILD_LOOKALIKE",
    "CHOOSE_GOAL",
    "CREATIVE_TEST",
    "DEFAULT_THRESHOLDS",
    "GO_BROAD",
    "LEARNING_SUCCESS",
    "NEEDS",
    "NEED_SEED_AUDIENCE",
    "NEED_TRAFFIC_SOURCE",
    "OPTIMIZING_COOLDOWN_HOURS",
    "RETARGET",
    "SCALE_UP",
    "SIGNAL_WINDOW_DAYS",
    "STRATEGIES",
    "STRATEGY_CODES",
    "WARM_START",
    "AccountMaturity",
    "AdSetPosture",
    "AudienceAssets",
    "LifecycleStage",
    "MaturityThresholds",
    "SignalHistory",
    "Strategy",
    "StrategyAdvice",
    "StrategyFn",
    "StrategyState",
    "advise",
    "cooldown_hours",
    "has_exited_learning",
    "maturity",
    "may_adjust",
    "may_scale",
    "stage",
]
