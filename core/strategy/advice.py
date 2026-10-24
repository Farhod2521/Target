"""What a strategy answers with, and the words it may use."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

NEED_SEED_AUDIENCE: Final = "seed_audience"
NEED_TRAFFIC_SOURCE: Final = "traffic_source"

NEEDS: Final[tuple[str, ...]] = (NEED_SEED_AUDIENCE, NEED_TRAFFIC_SOURCE)


@dataclass(frozen=True, slots=True)
class StrategyAdvice:
    """One direction worth taking, or worth preparing for."""

    strategy: str
    ready: bool = True
    needs: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        """The same advice as plain data, for whatever stores a night's."""
        return {
            "strategy": self.strategy,
            "ready": self.ready,
            "needs": list(self.needs),
            "evidence": dict(self.evidence),
        }


__all__ = [
    "NEEDS",
    "NEED_SEED_AUDIENCE",
    "NEED_TRAFFIC_SOURCE",
    "StrategyAdvice",
]
