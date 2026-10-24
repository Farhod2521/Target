"""Words of the source on the finished video's clock.

A planner names words by their number in the transcript it was shown; the
code works in seconds of the finished video. Everything that turns one
into the other - where a component starts, where its beats land, where
the picture punches in - goes through here, after the cuts are final.
"""

from collections.abc import Sequence
from typing import Any

from videokit import Cut

from core.montage.captions import SpokenWord


def word_times(
    words: tuple[SpokenWord, ...], cuts: Sequence[Cut]
) -> dict[int, tuple[float, float]]:
    """Each kept word's start and end in the finished video, by its number."""
    times: dict[int, tuple[float, float]] = {}
    cursor = 0.0
    for cut in cuts:
        offset = cursor - cut.start
        for index, word in enumerate(words):
            inside = word.start >= cut.start and word.end <= cut.end + 0.05
            if inside and index not in times:
                end = min(word.end, cut.end)
                times[index] = (round(word.start + offset, 3), round(end + offset, 3))
        cursor += cut.end - cut.start
    return times


def nearest_kept(
    index: int, times: dict[int, tuple[float, float]], count: int
) -> int | None:
    """The word itself if it stayed, else the closest one that did."""
    for distance in range(count + 1):
        for candidate in (index + distance, index - distance):
            if candidate in times:
                return candidate
    return None


def beat_times(
    beats: Any, times: dict[int, tuple[float, float]], count: int
) -> dict[str, float | list[float]]:
    """When each beat a planner gave lands: the start of its word in the
    finished video, or of the nearest word kept when its own was cut.

    A list beat keeps the items whose word found a place, in order; a
    beat with none is left out, and the component times it itself.
    """
    if beats is None:
        return {}
    out: dict[str, float | list[float]] = {}
    for name, given in beats.model_dump(exclude_none=True).items():
        words = given if isinstance(given, list) else [given]
        found = [
            times[kept][0]
            for word in words
            if (kept := nearest_kept(word, times, count)) is not None
        ]
        if found and isinstance(given, list):
            out[name] = found
        elif found:
            out[name] = found[0]
    return out
