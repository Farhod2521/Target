"""Something new on screen every few seconds, whatever the plan said."""

from collections.abc import Sequence
from itertools import pairwise
from typing import Final

from videokit import ComponentUse, Cut
from videokit.motion import PUNCH_CLEAR_END, PUNCH_CLEAR_START

from core.montage.captions import SpokenWord
from core.montage.word_clock import word_times

MAX_QUIET: Final = 3.5
_ALWAYS_THERE: Final = frozenset({"corner_logo", "progress_bar"})


def lively_punches(
    punches: Sequence[float],
    *,
    components: Sequence[ComponentUse],
    cuts: Sequence[Cut],
    words: tuple[SpokenWord, ...],
) -> tuple[float, ...]:
    """``punches`` with one added in every long quiet stretch, earliest first."""
    length = sum(cut.end - cut.start for cut in cuts)
    edges = _cut_edges(cuts)
    end = min((u.start for u in components if u.name == "end_card"), default=length)
    starts = [w[0] for w in word_times(words, cuts).values()]
    found = set(punches)
    while True:
        moments = sorted(
            {0.0, end, *edges, *found}
            | {u.start for u in components if u.name not in _ALWAYS_THERE}
        )
        added = False
        for low, high in pairwise(moments):
            if high > end or high - low <= MAX_QUIET:
                continue
            middle = (low + high) / 2
            fits = [
                at for at in starts if low + 1.0 < at < high - 1.0 and _clear(at, edges)
            ]
            if fits:
                found.add(min(fits, key=lambda at: abs(at - middle)))
                added = True
                break
        if not added:
            return tuple(sorted(found))


def _cut_edges(cuts: Sequence[Cut]) -> list[float]:
    edges, cursor = [], 0.0
    for cut in cuts:
        edges.append(round(cursor, 3))
        cursor += cut.end - cut.start
    return [*edges, round(cursor, 3)]


def _clear(at: float, edges: list[float]) -> bool:
    """Far enough from the cut it falls in for a punch to be kept there."""
    before = max(e for e in edges if e <= at)
    after = min(e for e in edges if e > at)
    return bool(at - before >= PUNCH_CLEAR_START and after - at >= PUNCH_CLEAR_END)
