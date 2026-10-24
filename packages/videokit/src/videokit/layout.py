"""The frame in pixels, its named zones, and sizes that keep their look.

Every size in this package is written for a 1080-pixel short side - the
size Reels and Shorts play at - and scaled from there. A caption drawn
68 px tall on a 1080x1920 frame is 45 px on 720x1280 and looks the same.

**Zones.** A vertical frame is cut into named bands, top to bottom, so a
caller says *where* something goes ("the lower third") and this module
alone knows the pixels. Two bands are never drawn on: the face
(``CENTER``) and the strips phones cover with their own buttons
(``SAFE_TOP``, ``SAFE_BOTTOM`` and the right-hand column,
:data:`SAFE_RIGHT_PX`). Subtitles have a band of their own.

**Layouts.** ``full`` is the footage over the whole frame. ``split_top``
moves it down (:data:`SPLIT_OFFSET_Y`) - the speaker into the bottom half -
and leaves the top half to a panel (``TOP_PANEL``), which must be opaque.

Converting a zone into Shotstack's terms - a box, ``position: center``
and an ``offset`` - happens in :func:`zone_box` and nowhere else.
"""

from typing import Any, Final

from videokit.models import AspectRatio, Resolution, Zone

# The short side of each preset Shotstack renders.
_SHORT_SIDE: Final[dict[Resolution, int]] = {"sd": 576, "hd": 720, "1080": 1080}
# Width over height, as a fraction.
_RATIO: Final[dict[AspectRatio, tuple[int, int]]] = {
    "9:16": (9, 16),
    "4:5": (4, 5),
    "1:1": (1, 1),
    "16:9": (16, 9),
}
DESIGN_SHORT_SIDE: Final = 1080


def frame_size(resolution: Resolution, aspect_ratio: AspectRatio) -> tuple[int, int]:
    """Width and height of the finished video, in pixels."""
    short = _SHORT_SIDE[resolution]
    across, down = _RATIO[aspect_ratio]
    if across <= down:
        return short, round(short * down / across)
    return round(short * across / down), short


def scaled(px: float, resolution: Resolution) -> int:
    """A size written for a 1080 short side, at this resolution."""
    return round(px * _SHORT_SIDE[resolution] / DESIGN_SHORT_SIDE)


# Each band's top and bottom on a 1080x1920 frame. Other frames take the
# same shares of their height.
DESIGN_HEIGHT: Final = 1920
# What Reels, Shorts and TikTok cover with their own buttons and captions
# on a vertical frame: the account line at the top, the caption and the
# sound bar at the bottom, the like/comment/share column at the right.
SAFE_TOP_PX: Final = 220
SAFE_BOTTOM_PX: Final = 420
SAFE_RIGHT_PX: Final = 140
ZONES: Final[dict[Zone, tuple[int, int]]] = {
    "SAFE_TOP": (0, SAFE_TOP_PX),
    # Just under the strip phones cover: where the small logo sits, in the
    # left-hand corner (the right one is under the app's buttons).
    "CORNER": (220, 360),
    "TOP_TITLE": (220, 720),
    "TOP_PANEL": (0, 960),
    "CENTER": (720, 1060),
    "LOWER_THIRD": (1060, 1280),
    "SUBTITLES": (1280, 1500),
    # Subtitles while the footage is split: the speaker's face is lower
    # then, and the line goes under the chin instead of over the mouth.
    "SUBTITLES_LOW": (1340, 1500),
    "SAFE_BOTTOM": (DESIGN_HEIGHT - SAFE_BOTTOM_PX, DESIGN_HEIGHT),
    # The last pixels of the frame, under everything the apps draw: room
    # for a thin progress line and nothing else.
    "EDGE": (DESIGN_HEIGHT - 16, DESIGN_HEIGHT),
    "FULL": (0, DESIGN_HEIGHT),
}
# Where the corner logo is drawn on a 1080x1920 frame: left, top, right,
# bottom. The same box as ``components/corner_logo/style.css`` - inside
# ``CORNER``, 48 px from the left edge, at most 220 by 110.
CORNER_LOGO_BOX: Final = (48, 235, 268, 345)
# Bands a component may be drawn in. The rest stay clear.
PLACEABLE: Final[frozenset[Zone]] = frozenset(
    {"CORNER", "TOP_TITLE", "TOP_PANEL", "LOWER_THIRD", "EDGE", "FULL"}
)
# How far ``split_top`` moves the footage, as Shotstack's ``offset.y``: a
# share of the frame's height, negative is down. Not a full quarter: a
# talking head's face sits a little above the middle of its own frame, and
# moved down a quarter it lands on the subtitles. This much keeps the eyes
# just under the panel; the subtitles drop to ``SUBTITLES_LOW``.
SPLIT_OFFSET_Y: Final = -0.10


def zone_span(zone: Zone) -> tuple[float, float]:
    """The band's top and bottom as shares of the frame's height."""
    top, bottom = ZONES[zone]
    return top / DESIGN_HEIGHT, bottom / DESIGN_HEIGHT


def zones_meet(one: Zone, other: Zone) -> bool:
    """Whether two bands share any row of pixels."""
    a_top, a_bottom = ZONES[one]
    b_top, b_bottom = ZONES[other]
    return a_top < b_bottom and b_top < a_bottom


def band(zone: Zone, top: int | None = None) -> tuple[int, int]:
    """The zone's band in design pixels, moved to start at ``top`` if given."""
    start, end = ZONES[zone]
    return (start, end) if top is None else (top, top + end - start)


def zone_box(
    zone: Zone,
    resolution: Resolution,
    aspect_ratio: AspectRatio,
    *,
    top: int | None = None,
) -> dict[str, Any]:
    """The clip fields that put an asset exactly over a zone - or over the
    zone's band moved to start at ``top`` (design pixels)."""
    start, end = band(zone, top)
    return band_box(start, end, resolution, aspect_ratio)


def band_box(
    start: float, end: float, resolution: Resolution, aspect_ratio: AspectRatio
) -> dict[str, Any]:
    """The clip fields that put an asset over a band, in design pixels."""
    width, height = frame_size(resolution, aspect_ratio)
    top, bottom = start / DESIGN_HEIGHT, end / DESIGN_HEIGHT
    middle = (top + bottom) / 2
    return {
        "width": width,
        "height": round((bottom - top) * height),
        "position": "center",
        "offset": {"x": 0, "y": round(0.5 - middle, 4)},
    }


def safe_area(aspect_ratio: AspectRatio) -> tuple[int, int, int, int] | None:
    """Left, top, right, bottom of what no app covers, in design pixels.

    Only a vertical frame has one: the apps that put their buttons over a
    video play it full screen. Elsewhere the whole frame is free.
    """
    if aspect_ratio != "9:16":
        return None
    return (
        0,
        SAFE_TOP_PX,
        DESIGN_SHORT_SIDE - SAFE_RIGHT_PX,
        DESIGN_HEIGHT - SAFE_BOTTOM_PX,
    )
