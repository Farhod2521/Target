"""Silences inside a kept stretch are cut out, leaving air at the edges."""

import pytest
from videokit import Cut

from core.montage import SpokenWord
from core.montage.pauses import (
    KEEP_AFTER,
    KEEP_BEFORE,
    MIN_PIECE_SECONDS,
    without_pauses,
)


def _said(*spans: tuple[float, float]) -> tuple[SpokenWord, ...]:
    return tuple(
        SpokenWord(text=f"w{i}", start=a, end=b) for i, (a, b) in enumerate(spans)
    )


def test_a_long_silence_between_two_words_is_cut_out() -> None:
    words = _said((0.2, 0.6), (0.7, 1.2), (2.0, 2.4), (2.5, 3.0))

    pieces = without_pauses([Cut(start=0.1, end=3.2, enter="slide")], words)

    assert [(p.start, p.end) for p in pieces] == [
        (0.1, round(1.2 + KEEP_AFTER, 3)),
        (round(2.0 - KEEP_BEFORE, 3), 3.2),
    ]
    # The stretch's transition stays on its first piece only.
    assert [p.enter for p in pieces] == ["slide", "none"]


@pytest.mark.parametrize("gap", [0.1, 0.3])
def test_a_breath_is_kept(gap: float) -> None:
    words = _said((0.2, 1.0), (1.0 + gap, 2.0))

    assert without_pauses([Cut(start=0.0, end=2.2)], words) == (
        Cut(start=0.0, end=2.2),
    )


def test_no_piece_shorter_than_the_least_is_made() -> None:
    """One short word, then a pause: cutting there would flicker."""
    words = _said((0.05, 0.2), (1.5, 2.5), (3.4, 4.4))

    pieces = without_pauses([Cut(start=0.0, end=4.6)], words)

    assert all(p.end - p.start >= MIN_PIECE_SECONDS for p in pieces)
    # The first pause is kept (its left piece would be 0.28 s); the second goes.
    assert [(p.start, p.end) for p in pieces] == [
        (0.0, round(2.5 + KEEP_AFTER, 3)),
        (round(3.4 - KEEP_BEFORE, 3), 4.6),
    ]


def test_the_push_in_carries_on_across_a_removed_pause() -> None:
    words = _said((0.0, 2.0), (3.0, 5.0))

    first, second = without_pauses([Cut(start=0.0, end=5.0, zoom=1.15)], words)

    assert first.zoom == 1.15
    assert second.zoom > first.zoom
    assert second.zoom == round(1.15 * (1 + 0.01 * (first.end - first.start)), 3)


def test_words_outside_the_stretch_do_not_cut_it() -> None:
    words = _said((0.0, 1.0), (5.0, 6.0))

    assert without_pauses([Cut(start=0.0, end=1.2)], words) == (
        Cut(start=0.0, end=1.2),
    )
