"""What is checked before a montage is sent to the renderer.

A render costs minutes and money, and a mistake in it is seen only by
watching the result. Everything that can be known from the edit alone is
checked here first; any problem stops the montage with its reason:

- **the opening**: the first frame is the picture, not black (no fade up,
  no flash over it), and the headline is up within :data:`HOOK_LATEST`;
- **text**: every text fits its box at a size no smaller than the
  smallest allowed for it (:data:`FLOORS` - measured in the brand's
  font, see :mod:`videokit.fit`), subtitles included;
- **zones**: no two components in the same band at the same moment;
- **props**: nothing required left blank, nothing drawn with nothing of
  the brand to show;
- **the call to action**: the button is on screen when the video ends;
- **safe zones**: on a vertical frame, nothing drawn where the apps put
  their own buttons (:func:`videokit.layout.safe_area`);
- **logos and buttons** (:mod:`videokit.preflight_logos`): every logo
  whole on its plate, its lettering at least 24 px where it stands for
  the name, and a button's tap circle clear of its words;
- **the face** (:mod:`videokit.preflight_faces`): nothing over the
  speaker's eyes or mouth;
- **contrast** (:mod:`videokit.preflight_contrast`): words over the
  footage readable against it, or on a dark backing.
"""

from collections.abc import Iterator
from itertools import combinations
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from videokit.captions import caption_px, text_width
from videokit.components import component
from videokit.components.lettering import lettering
from videokit.components.render import brand_values
from videokit.layout import (
    CORNER_LOGO_BOX,
    DESIGN_SHORT_SIDE,
    ZONES,
    frame_size,
    safe_area,
    zones_meet,
)
from videokit.models import ComponentUse, EditSpec
from videokit.motion import FLASH
from videokit.preflight_contrast import contrast_problems
from videokit.preflight_faces import face_problems
from videokit.preflight_logos import logo_problems

ProblemKind = Literal[
    "black_start",
    "late_hook",
    "text_overflow",
    "small_text",
    "zone_clash",
    "empty_props",
    "no_cta",
    "unsafe_zone",
    "logo_cut",
    "logo_text",
    "tap_on_text",
    "face_covered",
    "low_contrast",
]
# The headline is on screen this soon, or the feed has scrolled on.
HOOK_LATEST: Final = 0.3
# The smallest size each kind of text may be drawn at, for a 1080 short
# side: headlines, chips, subtitles, and the contacts under the button.
FLOORS: Final[dict[str, int]] = {
    "hook_title.text": 64,
    "hook_counter.value": 96,
    "hook_counter.pill": 64,
    "headline_slam.line": 56,
    "headline_slam.pill": 64,
    "stamp_badge.stamp": 56,
    "price_tag.price": 72,
    "checklist.title": 52,
    "checklist.items": 30,
    "phone_mockup.title": 48,
    "reach_globe.title": 64,
    "chips_list.title": 64,
    "end_card.card_name": 64,
    "chips_list.items": 36,
    "captions": 44,
    "cta_button.cta_contact_lines": 32,
}
_MOMENT: Final = 0.01
_BUTTONS: Final = frozenset({"cta_button", "end_cta"})


class Problem(BaseModel):
    """One thing wrong with an edit, said for staff."""

    model_config = ConfigDict(frozen=True)

    kind: ProblemKind
    subject: str
    at: float
    note: str


def preflight(spec: EditSpec, edit: dict[str, Any]) -> tuple[Problem, ...]:
    """Every problem with ``spec`` (as ``edit``, the body sent); none is fine."""
    return (
        *_opening(spec, edit),
        *_texts(spec),
        *_clashes(spec),
        *_empty(spec),
        *_cta(spec),
        *_unsafe(spec),
        *logo_problems(spec),
        *face_problems(spec),
        *contrast_problems(spec),
    )


def _opening(spec: EditSpec, edit: dict[str, Any]) -> Iterator[Problem]:
    for track in edit["timeline"]["tracks"]:
        for clip in track["clips"]:
            if clip["start"] > 0:
                continue
            asset = clip["asset"]
            footage = (
                asset.get("type") == "video" and asset.get("src") == spec.source_url
            )
            if footage and "in" in clip.get("transition", {}):
                yield Problem(
                    kind="black_start", subject="footage", at=0, note="fades in"
                )
            if asset.get("html") == FLASH["html"]:
                yield Problem(
                    kind="black_start", subject="flash", at=0, note="covers frame 0"
                )
    if not spec.components:
        return
    hooks = [u.start for u in spec.components if component(u.name).hook]
    if not hooks or min(hooks) > HOOK_LATEST:
        at = min(hooks, default=-1.0)
        yield Problem(
            kind="late_hook", subject="hook", at=at, note="no headline at once"
        )


def _texts(spec: EditSpec) -> Iterator[Problem]:
    for use in spec.components:
        item = component(use.name)
        shown = {**brand_values(spec.brand), **item.cased(use.props)}
        sized = lettering(item, shown, brand=spec.brand)
        for name in sized.overflow:
            yield Problem(
                kind="text_overflow",
                subject=f"{use.name}.{name}",
                at=use.start,
                note="does not fit its box at the smallest size",
            )
        for name, px in sized.sizes.items():
            floor = FLOORS.get(f"{use.name}.{name}", 0)
            if px < floor and name not in sized.overflow:
                yield Problem(
                    kind="small_text",
                    subject=f"{use.name}.{name}",
                    at=use.start,
                    note=f"{px}px under {floor}px",
                )
    if spec.captions and caption_px(spec) is None:
        yield Problem(
            kind="text_overflow",
            subject="captions",
            at=0,
            note="a subtitle line does not fit two rows",
        )


def _clashes(spec: EditSpec) -> Iterator[Problem]:
    front = [u for u in spec.components if component(u.name).layer == "front"]
    for one, other in combinations(front, 2):
        overlap = max(
            min(a_end, b_end) - max(a_start, b_start)
            for a_start, a_end in one.windows()
            for b_start, b_end in other.windows()
        )
        if overlap > _MOMENT and zones_meet(one.zone, other.zone):
            yield Problem(
                kind="zone_clash",
                subject=f"{one.name}+{other.name}",
                at=max(one.start, other.start),
                note=f"{one.zone} and {other.zone} at once",
            )


def _empty(spec: EditSpec) -> Iterator[Problem]:
    for use in spec.components:
        item = component(use.name)
        blank = [
            p.name
            for p in item.props
            if p.required and not str(use.props.get(p.name) or "").strip()
        ]
        if blank or not item.drawable(spec.brand):
            yield Problem(
                kind="empty_props",
                subject=use.name,
                at=use.start,
                note=", ".join(blank) or "nothing of the brand to show",
            )


def _cta(spec: EditSpec) -> Iterator[Problem]:
    if not spec.components:
        return
    end = spec.length
    if not any(u.name in _BUTTONS and _end(u) >= end - 0.05 for u in spec.components):
        yield Problem(
            kind="no_cta", subject="cta_button", at=end, note="no button at the end"
        )


def _unsafe(spec: EditSpec) -> Iterator[Problem]:
    area = safe_area(spec.aspect_ratio)
    if area is None:
        return
    boxes: list[tuple[str, float, tuple[int, int, int, int]]] = []
    for use in spec.components:
        item = component(use.name)
        if item.box is None:
            continue
        left, top, right, bottom = item.box
        zone_top = ZONES[use.zone][0]
        if use.name == "corner_logo":
            boxes.append((use.name, use.start, CORNER_LOGO_BOX))
        else:
            boxes.append(
                (use.name, use.start, (left, zone_top + top, right, zone_top + bottom))
            )
    if spec.captions:
        boxes.append(("captions", 0.0, _caption_rect(spec)))
    for name, at, (left, top, right, bottom) in boxes:
        if left < area[0] or top < area[1] or right > area[2] or bottom > area[3]:
            yield Problem(
                kind="unsafe_zone",
                subject=name,
                at=at,
                note=f"({left}, {top}, {right}, {bottom}) outside {area}",
            )


def _caption_rect(spec: EditSpec) -> tuple[int, int, int, int]:
    """The subtitles' band on the design frame, lower one included."""
    short = min(frame_size(spec.resolution, spec.aspect_ratio))
    width = round(text_width(spec) * DESIGN_SHORT_SIDE / short)
    left = (DESIGN_SHORT_SIDE - width) // 2
    top = min(ZONES["SUBTITLES"][0], ZONES["SUBTITLES_LOW"][0])
    bottom = max(ZONES["SUBTITLES"][1], ZONES["SUBTITLES_LOW"][1])
    return left, top, left + width, bottom


def _end(use: ComponentUse) -> float:
    return use.start + use.length
