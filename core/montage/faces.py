"""The faces found on the stills, moved into the finished video.

The planner's stills are taken from the source; a face on one is where
the speaker was at that second of the source. Once the cuts are final,
each still that was kept is a moment of the finished video, and its face
is mapped into the frame through the cut's crop and zoom
(:func:`videokit.faces.on_frame`).

**The zoom moves.** A cut creeps closer as it plays and may punch in
(:mod:`videokit.motion`), held on the face: the face grows about its own
middle and stays where it is. The mark is the face at the least zoom and
at the most in the second either side of the still, joined - however
big it is then, it is inside.

Stored on the montage as ``[source second, still width, still height,
box, guard, score]``, shares of the still (see :func:`stored`).
"""

from collections.abc import Sequence
from typing import Any, Final

from videokit import Cut
from videokit.faces import Face, joined, on_frame
from videokit.models import AspectRatio, FaceMark, Rect
from videokit.motion import PUNCH, PUSH_MAX, PUSH_PER_SECOND

from core.montage.corner import output_time

# A still stands for the footage this far either side of its moment.
SPAN: Final = 1.0
# Faces smaller than this share of the still's height are someone in the
# background, not the speaker.
MIN_HEIGHT: Final = 0.08


def stored(
    at: float, still: tuple[int, int], faces: Sequence[Face]
) -> list[Any] | None:
    """The speaker's face on one still, as the montage keeps it; None when
    there is none worth keeping (the largest face, if big enough)."""
    if not faces:
        return None
    face = faces[0]
    if face.box[3] - face.box[1] < MIN_HEIGHT:
        return None
    return [
        round(at, 3),
        still[0],
        still[1],
        list(face.box),
        list(face.guard),
        face.score,
    ]


def face_marks(
    stored_faces: Sequence[Sequence[Any]],
    *,
    cuts: Sequence[Cut],
    aspect_ratio: AspectRatio,
    punches: Sequence[float] = (),
) -> tuple[FaceMark, ...]:
    """Each kept still's face at its moment of the finished video."""
    marks = []
    for at, width, height, box, guard, _score in stored_faces:
        moment = output_time(cuts, float(at))
        if moment is None:
            continue
        cut = _cut_at(cuts, float(at))
        low, high = _zooms(cut, cuts, punches, moment)
        plain_box, plain_guard = (
            on_frame(tuple(rect), still=(width, height), aspect_ratio=aspect_ratio)
            for rect in (box, guard)
        )
        middle = _middle(plain_guard)
        boxes = [_grown_about(plain_box, middle, z) for z in (low, high)]
        guards = [_grown_about(plain_guard, middle, z) for z in (low, high)]
        marks.append(
            FaceMark(at=round(moment, 3), box=joined(boxes), guard=joined(guards))
        )
    return tuple(sorted(marks, key=lambda m: m.at))


def _middle(rect: Rect) -> tuple[float, float]:
    return (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2


def _grown_about(rect: Rect, middle: tuple[float, float], zoom: float) -> Rect:
    """``rect`` as it is drawn pushed in ``zoom`` times about ``middle``."""
    x, y = middle
    return (
        round(x + (rect[0] - x) * zoom, 1),
        round(y + (rect[1] - y) * zoom, 1),
        round(x + (rect[2] - x) * zoom, 1),
        round(y + (rect[3] - y) * zoom, 1),
    )


def _cut_at(cuts: Sequence[Cut], at: float) -> Cut:
    return next(c for c in cuts if c.start <= at < c.end)


def _zooms(
    cut: Cut, cuts: Sequence[Cut], punches: Sequence[float], moment: float
) -> tuple[float, float]:
    """The least and most zoom while the still stands for the footage: a
    second either side of its moment, within its cut."""
    start = 0.0
    for other in cuts:
        if other is cut:
            break
        start += other.end - other.start
    end = start + cut.end - cut.start
    zooms = [
        _zoom_at(cut, start, at, punches)
        for at in (max(start, moment - SPAN), moment, min(end, moment + SPAN))
    ]
    return min(zooms), max(zooms)


def _zoom_at(cut: Cut, start: float, at: float, punches: Sequence[float]) -> float:
    """The cut's zoom at ``at`` (finished video seconds): its own, crept
    closer as it plays, and punched in after an odd number of punches."""
    crept = cut.zoom * (1 + min(PUSH_PER_SECOND * (at - start), PUSH_MAX))
    punched = sum(1 for p in punches if start <= p <= at) % 2 == 1
    return float(crept * (PUNCH if punched else 1.0))
