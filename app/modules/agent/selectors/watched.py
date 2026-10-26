"""One group the watch has something to say about, and what its buttons act on."""

from dataclasses import dataclass

from core.agent.launch_watch import Watch
from core.agent.running_watch import Running
from core.metrics import Outcome


@dataclass(frozen=True, slots=True)
class Watched:
    """One new group, what is due about it, and what its buttons act on."""

    adset_id: str
    name: str
    campaign_id: str
    delete_level: str
    currency: str
    provider: str
    hours: int
    spend_minor: int
    results: int | None
    kind: Outcome
    daily_budget_minor: int | None
    in_review: bool
    watch: Watch
    running: Running | None = None


__all__ = ["Watched"]
