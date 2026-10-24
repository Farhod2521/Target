"""The frame in pixels, its named zones, and sizes that keep their look."""

from typing import Any, Final

from videokit.models import AspectRatio, Resolution, Zone

_SHORT_SIDE: Final[dict[Resolution, int]] = {"sd": 576, "hd": 720, "1080": 1080}
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


DESIGN_HEIGHT: Final = 1920
SAFE_TOP_PX: Final = 220
SAFE_BOTTOM_PX: Final = 420
SAFE_RIGHT_PX: Final = 140
ZONES: Final[dict[Zone, tuple[int, int]]] = {
    "SAFE_TOP": (0, SAFE_TOP_PX),
    "CORNER": (220, 360),
    "TOP_TITLE": (220, 720),
    "TOP_PANEL": (0, 960),
    "CENTER": (720, 1060),
    "LOWER_THIRD": (1060, 1280),
    "SUBTITLES": (1280, 1500),
    "SUBTITLES_LOW": (1340, 1500),
    "SAFE_BOTTOM": (DESIGN_HEIGHT - SAFE_BOTTOM_PX, DESIGN_HEIGHT),
    "EDGE": (DESIGN_HEIGHT - 16, DESIGN_HEIGHT),
    "FULL": (0, DESIGN_HEIGHT),
}
CORNER_LOGO_BOX: Final = (48, 235, 268, 345)
PLACEABLE: Final[frozenset[Zone]] = frozenset(
    {"CORNER", "TOP_TITLE", "TOP_PANEL", "LOWER_THIRD", "EDGE", "FULL"}
)
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
    """Left, top, right, bottom of what no app covers, in design pixels."""
    if aspect_ratio != "9:16":
        return None
    return (
        0,
        SAFE_TOP_PX,
        DESIGN_SHORT_SIDE - SAFE_RIGHT_PX,
        DESIGN_HEIGHT - SAFE_BOTTOM_PX,
    )
