"""How the footage moves: a slow push-in, punch-ins, and the way a new
part of the video comes in.

**Push-in.** Every cut creeps closer while it plays - a few per cent over
its length, never more than :data:`PUSH_MAX` - so a talking head is never
quite still. It starts from the cut's own ``zoom``, so the jump between
two takes of one shot stays hidden.

**Punch-in.** At a moment a planner marked as the point - the price, the
result - the picture steps :data:`PUNCH` closer at once and stays there;
a second mark in the same cut steps back out. A step too close to the
cut's start or end would read as a stutter, so it is left out.

**Transitions** (``Cut.enter``) mark a new part, never an ordinary cut:

- ``fade`` and ``slide`` are Shotstack's own (``fadeFast``,
  ``slideUpFast``), coming up out of the black background;
- ``zoom`` lands from :data:`ENTER_ZOOM` times closer in a third of a
  second (a scale tween);
- ``flash`` is a white frame that peaks on the cut and clears - an HTML5
  clip over everything;
- ``burst`` is both: the flash, and the picture landing from closer - a
  new part of the video, in place of the reference montage's colour
  glitch, which a renderer that only places clips cannot draw.

**Held on the face.** Shotstack scales a clip about its middle, which
pushes a face that is not in the middle out towards the edge. Where the
speaker's face is known (``EditSpec.faces``), every scale comes with an
``offset`` that keeps the face's middle where it was
(:func:`held_offset`): ``offset = ∓(scale - 1)·(face - ½)``, measured on
stage within a hundredth of the frame (docs/montage_spike2.md).

All of it is Shotstack ``scale`` tweens on the footage clips, by each
clip's own clock, and each clip's tweens run on from one another without
a jump: the renderer turns a jump between two tweens into a drift over
the first (measured on stage), so a punch-in is a cut of the clip
instead, the next clip starting at the new scale. A cut played as
several clips has its curve sliced at the boundaries, so the motion
carries on across them unbroken.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from videokit.layout import DESIGN_HEIGHT, DESIGN_SHORT_SIDE
from videokit.models import Cut, FaceMark, Layout, Transition

PUSH_PER_SECOND: Final = 0.01
PUSH_MAX: Final = 0.05
PUNCH: Final = 1.12
ENTER_ZOOM: Final = 1.25
ENTER_SECONDS: Final = 0.35
# A punch nearer than this to the cut's start or end is left out.
PUNCH_CLEAR_START: Final = 0.6
PUNCH_CLEAR_END: Final = 0.5
SHOTSTACK_IN: Final[dict[str, str]] = {"fade": "fadeFast", "slide": "slideUpFast"}
# The transitions that land from closer, and those that flash.
LANDS: Final = frozenset({"zoom", "burst"})
FLASHES: Final = frozenset({"flash", "burst"})
FLASH_BEFORE: Final = 0.1
FLASH_SECONDS: Final = 0.4
FLASH: Final[dict[str, str]] = {
    "type": "html5",
    "html": "<div id=f></div>",
    "css": (
        "html,body{margin:0;background:transparent}"
        "#f{position:absolute;top:0;left:0;right:0;bottom:0;"
        "background:#fff;opacity:0}"
    ),
    "js": (
        "gsap.timeline().to('#f',{opacity:0.9,duration:0.1,ease:'power2.out'})"
        ".to('#f',{opacity:0,duration:0.3,ease:'power2.in'});"
    ),
}


@dataclass(frozen=True, slots=True)
class Key:
    """The scale from ``low`` to ``high`` over ``[start, end)`` of a cut."""

    start: float
    end: float
    low: float
    high: float
    easing: str = ""


def cut_starts(cuts: tuple[Cut, ...]) -> list[float]:
    """Where each cut begins in the finished video."""
    starts, cursor = [], 0.0
    for cut in cuts:
        starts.append(round(cursor, 3))
        cursor += cut.end - cut.start
    return starts


def cut_keys(cut: Cut, *, at: float, punches: tuple[float, ...]) -> list[Key]:
    """The scale over ``cut``, which starts ``at`` in the finished video.

    ``punches`` are moments of the finished video; those inside it count.
    """
    length = cut.end - cut.start
    return scale_keys(
        length,
        base=cut.zoom,
        punches=tuple(p - at for p in punches if at <= p < at + length),
        enter=cut.enter,
    )


def scale_keys(
    length: float, *, base: float, punches: tuple[float, ...], enter: Transition
) -> list[Key]:
    """The scale over one cut of ``length`` seconds, by the cut's clock.

    ``punches`` are moments in the cut; those too near its edges are left out.
    """
    push = min(PUSH_PER_SECOND * length, PUSH_MAX)

    def at(moment: float) -> float:
        return base * (1 + push * moment / length)

    clear = sorted(
        p for p in punches if PUNCH_CLEAR_START <= p <= length - PUNCH_CLEAR_END
    )
    marks = [0.0, *clear, length]
    keys = []
    for index, (low, high) in enumerate(pairwise(marks)):
        step = PUNCH if index % 2 else 1.0
        keys.append(Key(low, high, at(low) * step, at(high) * step))
    if enter in LANDS and keys[0].end > ENTER_SECONDS:
        first = keys[0]
        landed = first.low + (first.high - first.low) * ENTER_SECONDS / first.end
        keys[0:1] = [
            Key(0.0, ENTER_SECONDS, landed * ENTER_ZOOM, landed, "easeOutCubic"),
            Key(ENTER_SECONDS, first.end, landed, first.high),
        ]
    return keys


def scale_tweens(keys: list[Key], low: float, high: float) -> list[dict[str, Any]]:
    """The part of ``keys`` inside ``[low, high)``, as tweens by that clip's clock.

    A key cut in two is cut where a straight line between its ends would
    be - exact for the push-in, near enough for a landing zoom's curve.
    """
    tweens = []
    for key in keys:
        a, b = max(key.start, low), min(key.end, high)
        if b - a <= 1e-6:
            continue
        span = key.end - key.start
        values = [
            key.low + (key.high - key.low) * (t - key.start) / span for t in (a, b)
        ]
        tween: dict[str, Any] = {
            "from": round(values[0], 4),
            "to": round(values[1], 4),
            "start": round(a - low, 3),
            "length": round(b - a, 3),
            "interpolation": "bezier" if key.easing else "linear",
        }
        if key.easing:
            tween["easing"] = key.easing
        tweens.append(tween)
    return tweens


def face_anchor(
    faces: Sequence[FaceMark], start: float, end: float
) -> tuple[float, float] | None:
    """The middle of the speaker's eyes and mouth over ``[start, end)``,
    as shares of the frame; None when no face was seen then."""
    seen = [m.guard for m in faces if start <= m.at < end]
    if not seen:
        return None
    x = sum((g[0] + g[2]) / 2 for g in seen) / len(seen) / DESIGN_SHORT_SIDE
    y = sum((g[1] + g[3]) / 2 for g in seen) / len(seen) / DESIGN_HEIGHT
    return round(x, 4), round(y, 4)


def held_offset(
    scale: list[dict[str, Any]], anchor: tuple[float, float]
) -> dict[str, list[dict[str, Any]]]:
    """Offset tweens that keep ``anchor`` in place under ``scale``'s tweens.

    Shotstack's ``offset`` is a share of the frame, up being positive; the
    offset is a straight function of the scale, so each offset tween runs
    with its scale tween's own timing and easing.
    """
    x, y = anchor

    def follow(t: dict[str, Any], lean: float) -> dict[str, Any]:
        return {
            **t,
            "from": round((t["from"] - 1) * lean, 4),
            "to": round((t["to"] - 1) * lean, 4),
        }

    return {
        "x": [follow(t, 0.5 - x) for t in scale],
        "y": [follow(t, y - 0.5) for t in scale],
    }


def steps(keys: list[Key]) -> list[float]:
    """Where the scale jumps rather than moves, by the cut's clock.

    The renderer eases from one tween's end to the next one's start over
    the earlier tween, so a jump inside one clip comes out as a slow drift
    (measured). A footage clip is cut at each of these instead, and the
    clip after it simply starts at the new scale.
    """
    return [b.start for a, b in pairwise(keys) if abs(a.high - b.low) > 1e-6]


def split_at(
    parts: list[tuple[float, float, Layout]], moments: list[float]
) -> list[tuple[float, float, Layout]]:
    """``parts`` cut again at each of ``moments`` that falls inside one."""
    out = []
    for low, high, layout in parts:
        edges = [low, *sorted(m for m in moments if low < m < high), high]
        out += [(a, b, layout) for a, b in pairwise(edges)]
    return out


def flash_clip(at: float) -> dict[str, Any]:
    """A white flash peaking on the cut at ``at``."""
    start = max(at - FLASH_BEFORE, 0.0)
    return {"asset": dict(FLASH), "start": round(start, 3), "length": FLASH_SECONDS}
