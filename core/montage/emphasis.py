"""Where the picture punches in: the words a planner marked as the point.

A planner names words (``emphasis``) by their number in the transcript;
each becomes the moment that word starts in the finished video. A word
that was cut out is let go rather than moved - a punch-in on the wrong
word is worse than none. Two closer than :data:`MIN_GAP_SECONDS` are one,
the first kept: punching in and out in a breath reads as a stutter.
"""

from collections.abc import Sequence
from typing import Final

from videokit import Cut

from core.montage.captions import SpokenWord
from core.montage.word_clock import word_times

MIN_GAP_SECONDS: Final = 1.5


def punch_times(
    indexes: Sequence[int], *, words: tuple[SpokenWord, ...], cuts: Sequence[Cut]
) -> tuple[float, ...]:
    """The finished video's moments to punch in on, earliest first."""
    times = word_times(words, cuts)
    found = sorted(times[i][0] for i in set(indexes) if i in times)
    kept: list[float] = []
    for moment in found:
        if not kept or moment - kept[-1] >= MIN_GAP_SECONDS:
            kept.append(moment)
    return tuple(kept)
