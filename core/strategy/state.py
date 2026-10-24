"""Everything a strategy is allowed to look at, as plain values."""

from dataclasses import dataclass

from core.strategy.lifecycle import LifecycleStage
from core.strategy.maturity import SignalHistory
from core.targeting import PlacementMode, TargetingMode


@dataclass(frozen=True, slots=True)
class AudienceAssets:
    """What the account holds at the provider, counted rather than listed."""

    ready_seeds: int = 0
    lookalikes: int = 0
    retargeting: int = 0
    has_traffic_source: bool = False


@dataclass(frozen=True, slots=True)
class AdSetPosture:
    """One ad set, as much of it as a strategy reads."""

    external_id: str
    stage: LifecycleStage
    delivery: str = ""
    counts_leads: bool = False
    creatives: int = 0
    mode: TargetingMode | None = None
    placement: PlacementMode | None = None


@dataclass(frozen=True, slots=True)
class StrategyState:
    """One account, assembled for the playbook."""

    history: SignalHistory
    assets: AudienceAssets
    adsets: tuple[AdSetPosture, ...] = ()
    active_campaigns: int = 0


__all__ = ["AdSetPosture", "AudienceAssets", "StrategyState"]
