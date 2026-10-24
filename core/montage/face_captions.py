"""Subtitle lines placed off the speaker's face (see
:mod:`core.montage.face_layout`): each in the free band under the chin,
else over the head, else under the mouth, at the largest size from its
usual one down to the smallest that fits the band - and split in two
where only one row fits.
"""

from collections.abc import Sequence
from typing import Final

from videokit import LayoutSpan
from videokit.faces import face_during, meets, moved
from videokit.fit import TextBox, lines_needed
from videokit.karaoke import FONT_PX, MIN_FONT_PX, STROKE_PX, WORD_GAP
from videokit.layout import DESIGN_HEIGHT, SAFE_RIGHT_PX, SAFE_TOP_PX, ZONES
from videokit.models import FaceMark, FontPreset, Rect

from core.montage.captions import Line

GAP: Final = 16
SAFE: Final = (SAFE_TOP_PX, ZONES["SAFE_BOTTOM"][0])
_CAPTION_X: Final = (SAFE_RIGHT_PX, 1080 - SAFE_RIGHT_PX)
_CAPTION_WIDTH: Final = round((_CAPTION_X[1] - _CAPTION_X[0]) * 0.94)
_ROW: Final = 1.15

# A subtitle line's place: band top, band bottom, size.
CaptionPlace = tuple[int, int, int]
# No place clear of the eyes and mouth: noted, and left to the checks.
NOWHERE: Final[CaptionPlace] = (-1, -1, -1)
Busy = tuple[float, float, Rect]


def place_caption(
    line: Line,
    when: tuple[float, float],
    marks: Sequence[FaceMark],
    spans: Sequence[LayoutSpan],
    busy: Sequence[Busy],
    font: FontPreset,
) -> CaptionPlace | None:
    """Where one subtitle line goes, shown over ``when``; None for its usual
    band, :data:`NOWHERE` when nothing clear of the eyes and mouth fits."""
    start, end = when
    face = face_over(marks, spans, start, end)
    if face is None:
        return None
    text = " ".join(word.text for word in line.words)
    box, guard = face
    taken = [r for s, e, r in busy if s < end and start < e]
    split = split_at(spans, (start + end) / 2) is not None
    top, bottom = ZONES["SUBTITLES_LOW" if split else "SUBTITLES"]
    usual = (_CAPTION_X[0], top, _CAPTION_X[1], bottom)
    if not meets(usual, box) and not any(meets(usual, r) for r in taken):
        return None
    for avoid in (box, guard):
        for low, high in _free(avoid, taken):
            for px in range(FONT_PX, MIN_FONT_PX - 1, -2):
                tall = _height(text, px, font)
                if tall is not None and tall <= high - low:
                    top = low if low >= avoid[3] else high - tall
                    return (round(top), round(top + tall), px)
    if not meets(usual, guard) and not any(meets(usual, r) for r in taken):
        return None
    return NOWHERE


def _free(face: Rect, taken: Sequence[Rect]) -> list[tuple[float, float]]:
    """Free bands across the subtitles' width: under the face first, then
    over it, then any other."""
    blocked = sorted(
        (r[1] - GAP, r[3] + GAP)
        for r in (face, *taken)
        if r[0] < _CAPTION_X[1] and _CAPTION_X[0] < r[2]
    )
    free, cursor = [], float(SAFE[0])
    for low, high in blocked:
        if low > cursor:
            free.append((cursor, min(low, SAFE[1])))
        cursor = max(cursor, high)
    if cursor < SAFE[1]:
        free.append((cursor, float(SAFE[1])))
    under = [f for f in free if f[0] >= face[3]]
    over = [f for f in free if f[1] <= face[1]]
    return under + over[::-1] + [f for f in free if f not in under and f not in over]


def _height(text: str, px: int, font: FontPreset) -> float | None:
    box = TextBox(
        selector=".l", px=px, min_px=px, width=_CAPTION_WIDTH, lines=2, gap=WORD_GAP
    )
    rows = lines_needed(text, box, preset=font, px=px)
    if rows is None or rows > 2:
        return None
    return float(rows * px * _ROW + 2 * STROKE_PX + 8)


def halves(line: Line) -> list[Line]:
    """``line`` as two, split between its words, each on its words' clock."""
    middle = (len(line.words) + 1) // 2
    return [
        Line(
            text=" ".join(w.text for w in part),
            start=part[0].start if index else line.start,
            end=part[-1].end if index == 0 else line.end,
            words=part,
        )
        for index, part in enumerate((line.words[:middle], line.words[middle:]))
    ]


def face_over(
    marks: Sequence[FaceMark], spans: Sequence[LayoutSpan], start: float, end: float
) -> tuple[Rect, Rect] | None:
    """The face over a stretch, moved down by a split it falls in."""
    face = face_during(marks, start, end)
    if face is None:
        return None
    split = split_at(spans, (start + end) / 2)
    if split is None:
        return (face[0], face[1])
    down = (split.shift if split.shift is not None else 0.10) * DESIGN_HEIGHT
    return moved(face[0], down), moved(face[1], down)


def split_at(spans: Sequence[LayoutSpan], at: float) -> LayoutSpan | None:
    return next(
        (s for s in spans if s.layout == "split_top" and s.start <= at < s.end), None
    )
