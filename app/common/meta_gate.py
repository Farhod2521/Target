"""Meta's app-wide call budget, kept in the cache every worker shares.

See :mod:`metaads.gate`: one process seeing the budget nearly gone holds
every background read back, and nothing a person is waiting on.
"""

from typing import Final

from metaads import gate

from app.common.cache import cache

KEY: Final = "meta:app-usage-stop"
# The sweeps' own reads. A press comes on the refresh queue and is not held.
BACKGROUND_TASKS: Final = frozenset(
    {
        "app.modules.ads.tasks.sync_ad_account_task",
        "app.modules.ads.tasks.sync_media_task",
        "app.modules.metrics.tasks.sync_today_task",
        "app.modules.metrics.tasks.sync_insights_task",
        "app.modules.metrics.tasks.sync_observed_task",
        "app.modules.metrics.tasks.refill_history_task",
        "app.modules.integrations.tasks.sync_pixels_task",
        "app.modules.integrations.tasks.sync_pixel_events_task",
        "app.modules.integrations.tasks.sync_audiences_task",
    }
)
PRESSED_QUEUE: Final = "refresh"


class CacheGate:
    def stopped(self) -> float | None:
        found = cache.get(KEY)
        return None if found is None else float(found)

    def stop(self, percent: float, seconds: int) -> None:
        cache.set(KEY, percent, timeout=seconds)


def install() -> None:
    gate.install(CacheGate())


def is_background(*, task: str, queue: str) -> bool:
    return task in BACKGROUND_TASKS and queue != PRESSED_QUEUE


__all__ = ["BACKGROUND_TASKS", "KEY", "CacheGate", "install", "is_background"]
