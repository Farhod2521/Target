"""Every number the montage planner is told, from where the code keeps it.

The prompt never carries a number of its own: what it says about time,
counts or the frame is filled in here from the constant the code acts
on, so the two cannot drift apart. The only numbers defined here are the
ones nothing but the planner acts on - how long a shot runs at each pace.
"""

from typing import Final

from videokit.components import component

from core.montage.conflicts import conflicts_text
from core.montage.emphasis import MIN_GAP_SECONDS
from core.montage.fitting import MAX_SHIFT_SECONDS
from core.montage.opening import HOOK_MAX_SECONDS
from core.montage.pauses import PAUSE_SECONDS
from core.montage.placement import END_SECONDS, LATE_BUTTON_SECONDS
from core.montage.plan import MAX_EMPHASIS
from core.montage.plan_v6 import MAX_EVENTS_V6
from core.montage.rhythm import MAX_QUIET
from core.montage.settle import MOST_CHANGES

# How long a shot runs before the next one, by pace: guidance for the
# planner only - the code does not cut on a clock.
SHOT_SECONDS: Final = {"dynamic": (2.0, 4.0), "calm": (4.0, 8.0)}


def limit_variables() -> dict[str, object]:
    """The prompt's numbers by name. The same for every montage, so they
    belong in the cached half of the prompt."""
    dynamic, calm = SHOT_SECONDS["dynamic"], SHOT_SECONDS["calm"]
    return {
        "max_events": str(MAX_EVENTS_V6),
        "max_emphasis": str(MAX_EMPHASIS),
        "max_quiet": _n(MAX_QUIET),
        "hook_max": _n(HOOK_MAX_SECONDS),
        "end_seconds": _n(END_SECONDS),
        "max_shift": _n(MAX_SHIFT_SECONDS),
        "max_transitions": str(MOST_CHANGES),
        "emphasis_gap": _n(MIN_GAP_SECONDS),
        "pause_seconds": _n(PAUSE_SECONDS),
        "late_button": _n(LATE_BUTTON_SECONDS),
        "sticker_max": str(component("sticker_fly").max_uses or ""),
        "dynamic_shot": f"{_n(dynamic[0])}-{_n(dynamic[1])}",
        "calm_shot": f"{_n(calm[0])}-{_n(calm[1])}",
        "conflicts": conflicts_text(),
    }


def _n(value: float) -> str:
    return f"{value:g}"
