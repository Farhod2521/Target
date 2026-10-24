"""Pauses taken out of the middle of a kept stretch."""

from collections.abc import Sequence
from itertools import pairwise
from typing import Final

from videokit import Cut
from videokit.motion import PUSH_MAX, PUSH_PER_SECOND

from core.montage.captions import SpokenWord

PAUSE_SECONDS: Final = 0.30
KEEP_BEFORE: Final = 0.06
KEEP_AFTER: Final = 0.08
MIN_PIECE_SECONDS: Final = 0.4
_INSIDE: Final = 0.05
_EPSILON: Final = 1e-6


def without_pauses(cuts: Sequence[Cut], words: Sequence[SpokenWord]) -> tuple[Cut, ...]:
    """``cuts`` with every long silence between two words taken out."""
    return tuple(piece for cut in cuts for piece in _pieces(cut, words))


def _pieces(cut: Cut, words: Sequence[SpokenWord]) -> list[Cut]:
    said = sorted(
        (
            w
            for w in words
            if w.start >= cut.start - _INSIDE and w.end <= cut.end + _INSIDE
        ),
        key=lambda w: w.start,
    )
    bounds: list[tuple[float, float]] = []
    opened = cut.start
    for before, after in pairwise(said):
        if after.start - before.end <= PAUSE_SECONDS + _EPSILON:
            continue
        closes = min(before.end + KEEP_AFTER, cut.end)
        reopens = max(after.start - KEEP_BEFORE, closes)
        if closes - opened < MIN_PIECE_SECONDS or cut.end - reopens < MIN_PIECE_SECONDS:
            continue
        bounds.append((opened, closes))
        opened = reopens
    bounds.append((opened, cut.end))
    if len(bounds) == 1:
        return [cut]
    pieces, played = [], 0.0
    for index, (start, end) in enumerate(bounds):
        creep = min(PUSH_PER_SECOND * played, PUSH_MAX)
        pieces.append(
            Cut(
                start=round(start, 3),
                end=round(end, 3),
                zoom=round(min(cut.zoom * (1 + creep), 1.5), 3),
                enter=cut.enter if index == 0 else "none",
            )
        )
        played += end - start
    return pieces


def _start(word: SpokenWord) -> float:
    return word.start
