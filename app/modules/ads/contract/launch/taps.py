"""What the wizard's screen chose and has not sent yet, kept for its launch.

The plan screen sends its answers together on «Davom etish», and the
pictures step sends its ticks with the proposal: until then they lived in the
browser's tab (``live/bridges/launch.ts``). They are kept here now, so a
reload or a second device lands where the owner left off. Nothing here is the
launch itself: lost, the screen shows the launch as saved.
"""

import uuid
from typing import Any, Final

from app.common.cache import cache

TAPS_KEY: Final = "launch-taps:{launch}"
# A wizard left open this long is started over from what the launch holds.
TAPS_SECONDS: Final = 30 * 24 * 60 * 60
PLAN_KEY: Final = "launch-plan:{launch}:{goal}"
# The plan read while the AI writes or the network creates: it cannot change meanwhile.
PLAN_SECONDS: Final = 10 * 60

# The plan screen's answers, as the screen names them.
PLAN_KEYS: Final = (
    "goal_mode",
    "goal_words",
    "goal",
    "method",
    "daily_budget",
    "start",
    "link_url",
    "phone",
    "chat_channel",
    "welcome_text",
    "chat_questions",
)


def read(launch_id: uuid.UUID) -> dict[str, Any]:
    found = cache.get(TAPS_KEY.format(launch=launch_id))
    return dict(found) if isinstance(found, dict) else {}


def write(launch_id: uuid.UUID, taps: dict[str, Any]) -> None:
    cache.set(TAPS_KEY.format(launch=launch_id), taps, TAPS_SECONDS)


def forget(launch_id: uuid.UUID) -> None:
    cache.delete(TAPS_KEY.format(launch=launch_id))


def tries(taps: dict[str, Any], poll: str) -> int:
    return int((taps.get("tries") or {}).get(poll) or 0)


def counted(taps: dict[str, Any], poll: str, value: int) -> None:
    taps["tries"] = {**(taps.get("tries") or {}), poll: value}


def kept_plan(launch_id: uuid.UUID, goal: str) -> Any:
    return cache.get(PLAN_KEY.format(launch=launch_id, goal=goal))


def keep_plan(launch_id: uuid.UUID, goal: str, plan: dict[str, Any]) -> None:
    cache.set(PLAN_KEY.format(launch=launch_id, goal=goal), plan, PLAN_SECONDS)


def forget_plan(launch_id: uuid.UUID, goal: str) -> None:
    cache.delete(PLAN_KEY.format(launch=launch_id, goal=goal))


__all__ = [
    "PLAN_KEYS",
    "counted",
    "forget",
    "forget_plan",
    "keep_plan",
    "kept_plan",
    "read",
    "tries",
    "write",
]
