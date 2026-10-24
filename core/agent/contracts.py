"""What the agent proposes, and whether it is allowed to."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from adskit import ExternalRef, Level

from core.metrics import Totals

SuggestionKind = Literal[
    "pause",
    "resume",
    "increase_budget",
    "decrease_budget",
    "swap_targeting",
    "narrow_targeting",
    "drop_audience",
    "new_ad",
    "new_picture",
]

ProviderAdvice = Literal["broader_audience",]


@dataclass(frozen=True, slots=True)
class Policy:
    """The thresholds one owner's decisions are made against."""

    window_days: int = 7
    usual_days: int = 14
    min_days: int = 3
    cooldown_hours: int = 48
    test_hours: int = 72
    max_per_run: int = 3
    rejected_quiet_days: int = 7
    budget_step_pct: int = 20
    waste_multiple: int = 3
    win_share_pct: int = 70
    lose_share_pct: int = 180
    constrained_share_pct: int = 90
    starved_share_pct: int = 60
    ctr_drop_pct: int = 30
    dead_segment_share_pct: int = 20


@dataclass(frozen=True, slots=True)
class Finding:
    """One change worth proposing, with the arithmetic that produced it."""

    kind: SuggestionKind
    rule: str
    ref: ExternalRef
    parent_id: str = ""
    weight: int = 0
    evidence: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> Level:
        """Which layer of the account this aims at."""
        return self.ref.level


@dataclass(frozen=True, slots=True)
class Aftermath:
    """The days since a change, in the counts a verdict is read from."""

    totals: Totals = field(default_factory=Totals)
    link_clicks: int = 0
    days: int = 0


@dataclass(frozen=True, slots=True)
class Verdict:
    """How one change turned out, with the numbers that say so."""

    outcome: str
    figures: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    """Whether a suggestion may be applied, and why not when it may not."""

    allowed: bool
    reason: str
