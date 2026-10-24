"""The speaker's face: found on a still, and where it sits in the frame."""

from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Final

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict

from videokit.layout import DESIGN_HEIGHT, DESIGN_SHORT_SIDE
from videokit.models import AspectRatio, FaceMark, Rect

MODEL: Final = Path(__file__).parent / "yunet" / "face_detection_yunet_2023mar.onnx"
SCORE: Final = 0.7
MAX_SIDE: Final = 640
_BROWS: Final = 0.35
_LIP: Final = 0.28
_SIDES: Final = 0.45
MARGIN: Final = 0.1
NEAREST_SECONDS: Final = 1.5

_RATIO: Final[dict[AspectRatio, float]] = {
    "9:16": 9 / 16,
    "4:5": 4 / 5,
    "1:1": 1.0,
    "16:9": 16 / 9,
}


class Face(BaseModel):
    """One face on one still, as shares of the still: left, top, right, bottom."""

    model_config = ConfigDict(frozen=True)

    box: Rect
    guard: Rect
    score: float


@cache
def _detector() -> cv2.FaceDetectorYN:
    return cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), SCORE, 0.3, 20)


def detect_faces(jpeg: bytes) -> list[Face]:
    """The faces on a still, the largest first; none when it does not read."""
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return []
    height, width = image.shape[:2]
    scale = min(1.0, MAX_SIDE / max(width, height))
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)))
        height, width = image.shape[:2]
    detector = _detector()
    detector.setInputSize((width, height))
    _found, rows = detector.detect(image)
    if rows is None:
        return []
    faces = [_face(row, width, height) for row in rows]
    return sorted(faces, key=lambda f: -(f.box[2] - f.box[0]) * (f.box[3] - f.box[1]))


def _face(row: np.ndarray, width: int, height: int) -> Face:
    x, y, w, h = (float(v) for v in row[:4])
    points = row[4:14].reshape(5, 2)
    eyes, mouth = points[:2], points[3:5]
    eye_y, mouth_y = float(eyes[:, 1].mean()), float(mouth[:, 1].mean())
    tall = max(mouth_y - eye_y, 1.0)
    apart = max(float(abs(eyes[0, 0] - eyes[1, 0])), 1.0)
    xs = [float(v) for v in (*eyes[:, 0], *mouth[:, 0])]
    guard = (
        min(xs) - _SIDES * apart,
        eye_y - _BROWS * tall,
        max(xs) + _SIDES * apart,
        mouth_y + _LIP * tall,
    )
    return Face(
        box=_shares((x, y, x + w, y + h), width, height),
        guard=_shares(guard, width, height),
        score=round(float(row[14]), 3),
    )


def _shares(rect: Rect, width: int, height: int) -> Rect:
    left, top, right, bottom = rect
    return (
        round(max(left, 0) / width, 4),
        round(max(top, 0) / height, 4),
        round(min(right, width) / width, 4),
        round(min(bottom, height) / height, 4),
    )


def on_frame(
    rect: Rect,
    *,
    still: tuple[int, int],
    aspect_ratio: AspectRatio,
    zoom: float = 1.0,
) -> Rect:
    """``rect`` (shares of a ``still`` of that size) in design pixels."""
    width, height = still
    frame = _RATIO[aspect_ratio]
    shown_w = min(width, height * frame) / zoom
    shown_h = min(height, width / frame) / zoom
    left, top = (width - shown_w) / 2, (height - shown_h) / 2
    x0, y0, x1, y1 = rect
    return (
        round((x0 * width - left) / shown_w * DESIGN_SHORT_SIDE, 1),
        round((y0 * height - top) / shown_h * DESIGN_HEIGHT, 1),
        round((x1 * width - left) / shown_w * DESIGN_SHORT_SIDE, 1),
        round((y1 * height - top) / shown_h * DESIGN_HEIGHT, 1),
    )


def joined(rects: Sequence[Rect]) -> Rect:
    """The smallest rect around all of ``rects``."""
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def face_during(
    marks: Sequence[FaceMark], start: float, end: float
) -> tuple[Rect, Rect] | None:
    """The face's box and guard over ``[start, end]``, with room around
    them; None when no face was seen then."""
    inside = [m for m in marks if start <= m.at <= end]
    if not inside and marks:
        middle = (start + end) / 2
        nearest = min(marks, key=lambda m: abs(m.at - middle))
        if abs(nearest.at - middle) - (end - start) / 2 <= NEAREST_SECONDS:
            inside = [nearest]
    if not inside:
        return None
    box = joined([m.box for m in inside])
    room = (box[3] - box[1]) * MARGIN
    return _grown(box, room), _grown(joined([m.guard for m in inside]), room)


def moved(rect: Rect, down: float) -> Rect:
    """``rect`` moved ``down`` pixels."""
    return (rect[0], rect[1] + down, rect[2], rect[3] + down)


def meets(one: Rect, other: Rect) -> bool:
    """Whether two rects share any area."""
    return (
        one[0] < other[2]
        and other[0] < one[2]
        and one[1] < other[3]
        and other[1] < one[3]
    )


def _grown(rect: Rect, by: float) -> Rect:
    return (rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by)
