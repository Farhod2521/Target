"""The small logo in the corner: when it shows, and which copy of it.

**When.** All through the video, except while something else is up at the
top of the frame - a headline, a panel (and the split footage under it),
the end card - or something that shows the brand itself, like the name
bar: two logos at once is one too many. A gap shorter than
:data:`SHORTEST` is skipped rather than blinked through.

**One clip per copy**: every stretch shown in the dark copy is one clip
that fades in and out of its stretches, the same for the light one.

**Which copy.** The one made for the footage behind the corner: the
dark-background copy over dark footage, the light one over light. The
brightness is measured on the stills the planner was shown, at the moments
that ended up inside each stretch, and the lightest of them decides: a
white logo is lost the moment the footage behind it turns light, a dark
one on dark footage only dims. With no still inside, the nearest one.
"""

from collections.abc import Sequence
from typing import Final

from videokit import Brand, ComponentUse, Cut, LayoutSpan, Zone
from videokit.components import component
from videokit.faces import face_during, meets
from videokit.layout import CORNER_LOGO_BOX, band
from videokit.logo_fit import corner_size
from videokit.models import FaceMark

CORNER: Final[Zone] = "CORNER"
SHORTEST: Final = 1.0
# Footage darker than this, on a 0-1 scale, gets the dark-background copy.
DARK_BELOW: Final = 0.5
# A component showing either of these is the brand on screen already.
_SHOWS_BRAND: Final = frozenset({"name", "logo"})


def corner_logos(
    *,
    components: Sequence[ComponentUse],
    layouts: Sequence[LayoutSpan],
    cuts: Sequence[Cut],
    brightness: Sequence[tuple[float, float]],
    brand: Brand,
    faces: Sequence[FaceMark] = (),
) -> tuple[ComponentUse, ...]:
    """The corner logo's clips. ``brightness`` is ``(source second, 0-1)``.

    A stretch whose copy of the logo cannot be drawn there with its
    lettering readable (:func:`videokit.logo_fit.corner_size`) goes
    without: a corner logo whose name is a smudge is worse than none.
    So does a stretch where the logo would sit on the speaker's face.
    """
    length = round(sum(cut.end - cut.start for cut in cuts), 3)
    seen = [
        (moment, value)
        for at, value in brightness
        if (moment := output_time(cuts, at)) is not None
    ]
    uses = []
    for start, end in free_spans(components=components, layouts=layouts, length=length):
        tone = "on_dark" if _brightness(start, end, seen) < DARK_BELOW else "on_light"
        copy = brand.logo_on_dark if tone == "on_dark" else brand.logo_on_light
        size = corner_size(copy or brand.logo)
        if size is None or _on_face(size, faces, start, end):
            continue
        uses.append((tone, round(start, 3), round(end, 3)))
    return tuple(_joined(uses))


def _joined(spans: list[tuple[str, float, float]]) -> list[ComponentUse]:
    """One clip for each copy of the logo, seen only in its own stretches:
    the logo is the heaviest thing a clip carries, and one copy per
    stretch would send it again for every gap."""
    out = []
    for tone in ("on_dark", "on_light"):
        own = [(start, end) for kind, start, end in spans if kind == tone]
        if not own:
            continue
        first, last = own[0][0], own[-1][1]
        out.append(
            ComponentUse(
                name="corner_logo",
                zone=CORNER,
                start=first,
                length=round(last - first, 3),
                props={tone: "1"},
                beats={"shows": [moment for span in own for moment in span]}
                if len(own) > 1
                else {},
            )
        )
    return sorted(out, key=lambda use: use.start)


def free_spans(
    *,
    components: Sequence[ComponentUse],
    layouts: Sequence[LayoutSpan],
    length: float,
) -> list[tuple[float, float]]:
    """The stretches of ``[0, length]`` with nothing else at the top and
    no other logo on screen."""
    corner_top, corner_bottom = band(CORNER)
    over = [
        u
        for u in components
        if _meets_corner(band(u.zone, u.top), corner_top, corner_bottom)
        or _SHOWS_BRAND & set(component(u.name).shows_brand)
    ]
    busy = sorted(
        [(u.start, u.start + u.length) for u in over]
        + [(s.start, s.end) for s in layouts if s.layout == "split_top"]
    )
    free, cursor = [], 0.0
    for start, end in busy:
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length:
        free.append((cursor, length))
    return [(start, end) for start, end in free if end - start >= SHORTEST]


def output_time(cuts: Sequence[Cut], at: float) -> float | None:
    """Where a second of the source plays in the finished video, if it does."""
    cursor = 0.0
    for cut in cuts:
        if cut.start <= at < cut.end:
            return float(cursor + at - cut.start)
        cursor += cut.end - cut.start
    return None


def _brightness(start: float, end: float, seen: Sequence[tuple[float, float]]) -> float:
    inside = [value for moment, value in seen if start <= moment < end]
    if inside:
        return max(inside)
    if not seen:
        return 0.0
    middle = (start + end) / 2
    return min(seen, key=lambda item: abs(item[0] - middle))[1]


def _meets_corner(span: tuple[int, int], top: int, bottom: int) -> bool:
    return span[0] < bottom and top < span[1]


def _on_face(
    size: tuple[int, int], faces: Sequence[FaceMark], start: float, end: float
) -> bool:
    """Whether the corner logo, this big, would sit on the face then."""
    face = face_during(faces, start, end)
    if face is None:
        return False
    left, top = CORNER_LOGO_BOX[0], CORNER_LOGO_BOX[1]
    return bool(meets((left, top, left + size[0], top + size[1]), face[0]))
