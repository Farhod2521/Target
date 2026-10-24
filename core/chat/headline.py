"""Which figure the week is about, when any of them is."""

from typing import Final

from core.chat.report import WeekFigures
from core.metrics import Movement, is_beyond_noise

HEADLINE_ORDER: Final = ("cpl",)


def headline_for(
    *,
    moves: dict[str, Movement],
    now: WeekFigures,
    before: WeekFigures,
) -> str:
    """Which figure this week is about, or nothing when none of them is."""
    counts = {
        "cpl": (now.results, before.results),
    }
    for key in HEADLINE_ORDER:
        move = moves.get(key)
        count_now, count_before = counts[key]
        if (
            move is not None
            and move.direction != "flat"
            and is_beyond_noise(
                percent=move.percent, now=count_now, before=count_before
            )
        ):
            return key
    return ""
