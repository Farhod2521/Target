"""Components laid onto tracks, and footage laid out around them.

**Tracks.** Two components on screen at once need two tracks - Shotstack
plays one clip per track at a time. Each component goes onto the first
track that is free for its whole stretch; backdrops (an end card) get
tracks of their own below every other component, so whatever is drawn
over them stays visible.

**Layouts.** A stretch in ``split_top`` moves the footage down a quarter
of the frame for exactly that stretch. A kept stretch of the source that
crosses into or out of one is played as two clips, cut at the boundary -
same source, same zoom, only the position changes.
"""

from collections.abc import Callable
from itertools import pairwise
from typing import Any

from videokit.components import component, component_clip
from videokit.layout import SPLIT_OFFSET_Y
from videokit.models import ComponentUse, EditSpec, Layout, LayoutSpan

# Times are rounded to the millisecond where spans and components are made.
SAME_MOMENT = 0.002


def component_tracks(spec: EditSpec) -> list[dict[str, Any]]:
    """Tracks of component clips, top first: front ones, then decorations,
    then backdrops."""
    lanes = [
        lane
        for layer in ("front", "decor", "backdrop")
        for lane in _lanes(
            [use for use in spec.components if component(use.name).layer == layer]
        )
    ]
    return [{"clips": [_clip(use, spec) for use in lane]} for lane in lanes]


def _lanes(uses: list[ComponentUse]) -> list[list[ComponentUse]]:
    lanes: list[list[ComponentUse]] = []
    for use in sorted(uses, key=lambda item: (item.start, item.name)):
        free = next(
            (
                lane
                for lane in lanes
                if lane[-1].start + lane[-1].length <= use.start + 1e-6
            ),
            None,
        )
        if free is None:
            lanes.append([use])
        else:
            free.append(use)
    return lanes


def _clip(use: ComponentUse, spec: EditSpec) -> dict[str, Any]:
    return component_clip(
        component(use.name),
        props=use.props,
        brand=spec.brand,
        zone=use.zone,
        start=use.start,
        length=use.length,
        resolution=spec.resolution,
        aspect_ratio=spec.aspect_ratio,
        top=use.top,
        marks={"scrim": "1"} if use.scrim else None,
        beats=use.beats,
    )


def pieces(
    start: float, end: float, spans: tuple[LayoutSpan, ...]
) -> list[tuple[float, float, Layout]]:
    """``[start, end)`` cut wherever a layout span begins or ends inside it."""
    edges = sorted(
        {start, end}
        | {at for span in spans for at in (span.start, span.end) if start < at < end}
    )
    out: list[tuple[float, float, Layout]] = []
    for low, high in pairwise(edges):
        middle = (low + high) / 2
        layout: Layout = next(
            (span.layout for span in spans if span.start <= middle < span.end),
            "full",
        )
        if out and out[-1][2] == layout:
            out[-1] = (out[-1][0], high, layout)
        else:
            out.append((low, high, layout))
    return out


def placed(
    clip: dict[str, Any], layout: Layout, shift: float | None = None
) -> dict[str, Any]:
    """A footage clip moved for its layout, as far as the span says - on
    top of any offset that holds the face (see :mod:`videokit.motion`)."""
    if layout != "split_top":
        return clip
    down = SPLIT_OFFSET_Y if shift is None else -shift
    held = clip.get("offset")
    if not isinstance(held, dict) or not isinstance(held.get("y"), list):
        return {**clip, "offset": {"x": 0, "y": round(down, 4)}}
    moved = [
        {**t, "from": round(t["from"] + down, 4), "to": round(t["to"] + down, 4)}
        for t in held["y"]
    ]
    return {**clip, "offset": {"x": held["x"], "y": moved}}


def shift_at(spans: tuple[LayoutSpan, ...], at: float) -> float | None:
    """How far the split covering ``at`` moves the footage, if it says."""
    return next(
        (s.shift for s in spans if s.layout == "split_top" and s.start <= at < s.end),
        None,
    )


def within_limit(
    spec: EditSpec, *, limit: int, size: Callable[[EditSpec], int]
) -> tuple[EditSpec, tuple[ComponentUse, ...]]:
    """``spec`` with graphics left out, latest first, until it fits ``limit``.

    What is still on screen when the video ends - the closing card and its
    button - is never left out. What was is returned, so a caller can say
    so. A spec that cannot be made to fit comes back as small as it got.
    """
    end = spec.length
    dropped: list[ComponentUse] = []
    while size(spec) > limit:
        optional = [
            use for use in spec.components if use.start + use.length < end - 0.01
        ]
        if not optional:
            break
        last = max(optional, key=lambda use: (use.start, use.name))
        spec = spec.model_copy(
            update={
                "components": tuple(u for u in spec.components if u is not last),
                # A panel's stretch goes with it: footage moved down for a
                # panel that is not there leaves a black band on top.
                "layouts": tuple(
                    span for span in spec.layouts if not _spans(span, last)
                ),
            }
        )
        dropped.append(last)
    return spec, tuple(dropped)


def _spans(span: LayoutSpan, use: ComponentUse) -> bool:
    """Whether ``span`` is the stretch laid out for ``use``."""
    return (
        abs(span.start - use.start) < SAME_MOMENT
        and abs(span.end - (use.start + use.length)) < SAME_MOMENT
    )
