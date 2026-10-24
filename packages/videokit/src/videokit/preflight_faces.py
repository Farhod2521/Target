"""The check before a render that the speaker's eyes and mouth stay clear.

Apart from :mod:`videokit.preflight` only to keep each file short.
**face_covered**: a component's content, or a subtitle line, over the
part of the face never to be covered (:attr:`videokit.models.FaceMark.guard`)
while it is on screen - the face moved down where the footage is split.
Nothing is checked over a backdrop (the closing card hides the footage),
or with no face found.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING

from videokit.captions import text_width
from videokit.components import component
from videokit.faces import face_during, meets, moved
from videokit.layout import (
    CORNER_LOGO_BOX,
    DESIGN_HEIGHT,
    DESIGN_SHORT_SIDE,
    SPLIT_OFFSET_Y,
    ZONES,
    band,
    frame_size,
)
from videokit.logo_fit import corner_size
from videokit.models import ComponentUse, EditSpec, Rect

if TYPE_CHECKING:
    from videokit.preflight import Problem


def face_problems(spec: EditSpec) -> Iterator["Problem"]:
    """Every element over the eyes or the mouth."""
    from videokit.preflight import Problem

    if not spec.faces:
        return
    for use in spec.components:
        if component(use.name).layer != "front" or _under_backdrop(use, spec):
            continue
        rect = _rect(use, spec)
        if rect is not None and any(
            _covers(spec, rect, start, end) for start, end in use.windows()
        ):
            yield Problem(
                kind="face_covered", subject=use.name, at=use.start, note=_note(rect)
            )
    short = min(frame_size(spec.resolution, spec.aspect_ratio))
    half = round(text_width(spec) * DESIGN_SHORT_SIDE / short / 2)
    left, right = DESIGN_SHORT_SIDE // 2 - half, DESIGN_SHORT_SIDE // 2 + half
    for line in spec.captions:
        low = _shift(spec, (line.start + line.end) / 2) is not None
        top, bottom = (
            (line.top, line.bottom)
            if line.top is not None and line.bottom is not None
            else ZONES["SUBTITLES_LOW" if low else "SUBTITLES"]
        )
        rect = (left, top, right, bottom)
        if _covers(spec, rect, line.start, line.end):
            yield Problem(
                kind="face_covered", subject="captions", at=line.start, note=_note(rect)
            )


def _rect(use: ComponentUse, spec: EditSpec) -> Rect | None:
    if use.name == "corner_logo":
        copy = (
            spec.brand.logo_on_dark
            if use.props.get("on_dark")
            else spec.brand.logo_on_light
        )
        size = corner_size(copy or spec.brand.logo)
        if size is None:
            return None
        x, y = CORNER_LOGO_BOX[0], CORNER_LOGO_BOX[1]
        return (x, y, x + size[0], y + size[1])
    box = component(use.name).box
    if box is None:
        return None
    start = band(use.zone, use.top)[0]
    return (box[0], start + box[1], box[2], start + box[3])


def _covers(spec: EditSpec, rect: Rect, start: float, end: float) -> bool:
    face = face_during(spec.faces, start, end)
    if face is None:
        return False
    guard = face[1]
    down = _shift(spec, (start + end) / 2)
    if down is not None:
        guard = moved(guard, down * DESIGN_HEIGHT)
    return bool(meets(rect, guard))


def _shift(spec: EditSpec, at: float) -> float | None:
    """How far the footage is moved down at ``at``, if it is split."""
    for span in spec.layouts:
        if span.layout == "split_top" and span.start <= at < span.end:
            return span.shift if span.shift is not None else -SPLIT_OFFSET_Y
    return None


def _under_backdrop(use: ComponentUse, spec: EditSpec) -> bool:
    return any(
        component(u.name).layer == "backdrop"
        and u.start <= use.start + 1e-6
        and use.start + use.length <= u.start + u.length + 1e-6
        for u in spec.components
    )


def _note(rect: Rect) -> str:
    left, top, right, bottom = (round(v) for v in rect)
    return f"({left}, {top}, {right}, {bottom}) on the eyes or mouth"
