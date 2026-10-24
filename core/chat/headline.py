"""Which figure the week is about, when any of them is.

Beside :mod:`core.chat.report`, which owns the week's shape. This is
the other question - not what the figures are, but whether one of them
has moved enough to lead with, and that is a judgement rather than a
measurement.

No Django, like everything under ``core``.
"""

from typing import Final

from core.chat.report import WeekFigures
from core.metrics import Movement, is_beyond_noise

# The figures a headline can be about, in the order they are preferred.
#
# There were two, and the cost per qualified lead was first: it is the
# figure this product exists to compute, with the plain cost as the
# fallback on a week nobody had marked yet. The marking is withdrawn -
# see `templates/leads/partials/_live.html` - so the fallback is the whole
# list, and a report cannot lead with a figure whose only source no screen
# can write. Restoring it is putting the key back at the front here and
# uncommenting the count beside it in :func:`headline_for`.
#
#     HEADLINE_ORDER: Final = ("cpql", "cpl")
HEADLINE_ORDER: Final = ("cpl",)


def headline_for(
    *,
    moves: dict[str, Movement],
    now: WeekFigures,
    before: WeekFigures,
) -> str:
    """Which figure this week is about, or nothing when none of them is.

    The figure is not taken on trust: it is checked against the count it
    was divided by, so a cost built on two leads is refused and the week
    gets no headline and no explanation rather than a confident sentence
    about noise.

    There were two candidates, preferred in order - see
    :data:`HEADLINE_ORDER`, where the withdrawn one is kept.
    """
    counts = {
        # "cpql": (now.qualified, before.qualified),
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
