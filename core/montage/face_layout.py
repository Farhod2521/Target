"""Graphics and subtitles moved off the speaker's face."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from videokit import ComponentUse, LayoutSpan
from videokit.components import component
from videokit.faces import face_during, meets
from videokit.layout import DESIGN_HEIGHT, ZONES, band
from videokit.models import FaceMark, FontPreset, Rect

from core.montage.captions import Line
from core.montage.face_captions import (
    GAP,
    NOWHERE,
    SAFE,
    Busy,
    CaptionPlace,
    face_over,
    halves,
    place_caption,
    split_at,
)

PANEL_BOTTOM: Final = ZONES["TOP_PANEL"][1]
MAX_SPLIT: Final = 480
TIME_STEP: Final = 0.25
MAX_DELAY: Final = 1.5
_MOVABLE: Final = frozenset({"lower_third", "cta_button"})


@dataclass(frozen=True, slots=True)
class Arranged:
    """Where everything went, and what had to give."""

    components: tuple[ComponentUse, ...]
    layouts: tuple[LayoutSpan, ...]
    captions: tuple[CaptionPlace | None, ...]
    notes: tuple[str, ...] = field(default=())
    lines: tuple[Line, ...] = field(default=())
    dropped: tuple[ComponentUse, ...] = field(default=())


def arrange(
    *,
    components: Sequence[ComponentUse],
    layouts: Sequence[LayoutSpan],
    lines: Sequence[Line],
    marks: Sequence[FaceMark],
    font: FontPreset,
    caption_shift: float = 0.0,
) -> Arranged:
    """``components``, ``layouts`` and subtitle ``lines`` kept off the face."""
    if not marks:
        return Arranged(
            tuple(components), tuple(layouts), (None,) * len(lines), lines=tuple(lines)
        )
    given: list[str] = []
    gone: list[ComponentUse] = []
    while True:
        result, crowded = _once(
            components, layouts, lines, marks, font, caption_shift, (given, gone)
        )
        if not crowded:
            return result
        for span in crowded:
            given.append(f"panel at {span.start:.1f}s left out: no room for subtitles")
        gone += [c for c in components if _panel_of(c, crowded)]
        components = [c for c in components if not _panel_of(c, crowded)]
        layouts = [s for s in layouts if s not in crowded]


def _panel_of(use: ComponentUse, spans: Sequence[LayoutSpan]) -> bool:
    return bool(component(use.name).layout) and any(
        abs(use.start - s.start) < 0.01 for s in spans
    )


def _once(
    components: Sequence[ComponentUse],
    layouts: Sequence[LayoutSpan],
    lines: Sequence[Line],
    marks: Sequence[FaceMark],
    font: FontPreset,
    caption_shift: float,
    given: tuple[Sequence[str], Sequence[ComponentUse]],
) -> tuple[Arranged, list[LayoutSpan]]:
    """One arrangement, and the splits a subtitle found no room in."""
    notes: list[str] = list(given[0])
    dropped: list[ComponentUse] = list(given[1])
    spans, uses = _splits(layouts, components, marks, (notes, dropped))
    busy: list[Busy] = [
        (u.start, u.start + u.length, _content(u))
        for u in uses
        if u.name not in _MOVABLE and component(u.name).layer == "front"
    ]
    placed: list[ComponentUse] = []
    for use in sorted(uses, key=lambda u: u.start):
        if use.name not in _MOVABLE or _under_card(use, uses):
            placed.append(use)
            continue
        moved_use = _moved(use, marks, spans, busy)
        if moved_use is None:
            notes.append(
                f"{use.name} at {use.start:.1f}s left out: no room off the face"
            )
            dropped.append(use)
            continue
        placed.append(moved_use)
        busy.append(
            (moved_use.start, moved_use.start + moved_use.length, _content(moved_use))
        )
    drawn: list[Line] = []
    places: list[CaptionPlace | None] = []
    crowded: list[LayoutSpan] = []
    queue = list(lines)
    while queue:
        line = queue.pop(0)
        start = max(line.start + caption_shift, 0.0)
        end = max(line.end + caption_shift, start + 0.01)
        place = place_caption(line, (start, end), marks, spans, busy, font)
        if place == NOWHERE and len(line.words) > 1:
            queue[:0] = halves(line)
            continue
        if place == NOWHERE:
            split = split_at(spans, (start + end) / 2)
            if split is not None:
                original = next(s for s in layouts if abs(s.start - split.start) < 0.01)
                if original not in crowded:
                    crowded.append(original)
            notes.append(f"subtitle at {start:.1f}s: no room off the eyes and mouth")
            place = None
        drawn.append(line)
        places.append(place)
    arranged = Arranged(
        tuple(placed),
        tuple(spans),
        tuple(places),
        tuple(notes),
        lines=tuple(drawn),
        dropped=tuple(dropped),
    )
    return arranged, crowded


def _splits(
    layouts: Sequence[LayoutSpan],
    uses: Sequence[ComponentUse],
    marks: Sequence[FaceMark],
    said: tuple[list[str], list[ComponentUse]],
) -> tuple[list[LayoutSpan], list[ComponentUse]]:
    """Each split moved just far enough; a panel that cannot clear the eyes
    goes, with its split - noted, and added to what was left out (``said``)."""
    notes, dropped = said
    spans, gone = [], []
    for span in layouts:
        face = face_during(marks, span.start, span.end)
        if span.layout != "split_top" or face is None:
            spans.append(span)
            continue
        _box, guard = face
        down = max(0.0, PANEL_BOTTOM + GAP - guard[1])
        if down > MAX_SPLIT:
            gone.append(span)
            notes.append(f"panel at {span.start:.1f}s left out: the face is too high")
            continue
        spans.append(span.model_copy(update={"shift": round(down / DESIGN_HEIGHT, 4)}))
    kept = []
    for u in uses:
        if any(
            abs(u.start - s.start) < 0.01 and component(u.name).layout for s in gone
        ):
            dropped.append(u)
        else:
            kept.append(u)
    return spans, kept


def _moved(
    use: ComponentUse,
    marks: Sequence[FaceMark],
    spans: Sequence[LayoutSpan],
    busy: Sequence[Busy],
) -> ComponentUse | None:
    """``use`` where it is clear of the face, a little later if need be."""
    item = component(use.name)
    left, inner_top, right, inner_bottom = item.box or (0, 0, 1080, 220)
    delay = 0.0
    while delay <= MAX_DELAY + 1e-6:
        start = use.start + delay
        end = start + use.length
        face = face_over(marks, spans, start, end)
        if face is None:
            return (
                use if delay == 0 else use.model_copy(update={"start": round(start, 3)})
            )
        box, guard = face
        default = band(use.zone)[0]
        tops = [
            default,
            round(box[3] + GAP - inner_top),
            round(box[1] - GAP - inner_bottom),
        ]
        tops += [
            round(guard[3] + GAP - inner_top),
            round(guard[1] - GAP - inner_bottom),
        ]
        for avoid in (box, guard):
            for top in tops:
                rect = (left, top + inner_top, right, top + inner_bottom)
                if _fits(rect, avoid, start, end, busy):
                    return use.model_copy(
                        update={
                            "start": round(start, 3),
                            "top": None if top == default else top,
                        }
                    )
        delay += TIME_STEP
    return None


def _fits(
    rect: Rect, face: Rect, start: float, end: float, busy: Sequence[Busy]
) -> bool:
    return (
        SAFE[0] <= rect[1]
        and rect[3] <= SAFE[1]
        and not meets(rect, face)
        and not any(
            s < end and start < e and meets(rect, other) for s, e, other in busy
        )
    )


def _content(use: ComponentUse) -> Rect:
    """Where ``use`` draws, in design pixels."""
    left, top, right, bottom = component(use.name).box or (0, 0, 1080, 0)
    start = band(use.zone, use.top)[0]
    return (left, start + top, right, start + bottom)


def _under_card(use: ComponentUse, uses: Sequence[ComponentUse]) -> bool:
    """Whether a backdrop hides the footage all the while ``use`` is up."""
    return any(
        component(u.name).layer == "backdrop"
        and u.start <= use.start + 1e-6
        and use.start + use.length <= u.start + u.length + 1e-6
        for u in uses
    )
