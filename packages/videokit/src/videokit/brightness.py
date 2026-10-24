"""How light the footage is behind something drawn over it - the corner
logo, a headline, a subtitle line - read off a still."""

import io

from PIL import Image, UnidentifiedImageError

from videokit.layout import CORNER_LOGO_BOX, DESIGN_HEIGHT, DESIGN_SHORT_SIDE
from videokit.models import AspectRatio

SHARE = 0.75

_RATIO: dict[AspectRatio, float] = {
    "9:16": 9 / 16,
    "4:5": 4 / 5,
    "1:1": 1.0,
    "16:9": 16 / 9,
}


def corner_brightness(
    jpeg: bytes, *, aspect_ratio: AspectRatio = "9:16", zoom: float = 1.0
) -> float | None:
    """How light the corner's lighter part is, 0-1; None when the still
    does not read."""
    return region_light(jpeg, CORNER_LOGO_BOX, aspect_ratio=aspect_ratio, zoom=zoom)


def region_light(
    jpeg: bytes,
    rect: tuple[float, float, float, float],
    *,
    aspect_ratio: AspectRatio = "9:16",
    zoom: float = 1.0,
) -> float | None:
    """How light the lighter part of ``rect`` (design pixels of the
    finished frame) is on a still of the source, 0-1; None when the still
    does not read or the rect is off it."""
    try:
        with Image.open(io.BytesIO(jpeg)) as still:
            grey = still.convert("L")
    except (UnidentifiedImageError, OSError):
        return None
    width, height = grey.size
    frame = _RATIO[aspect_ratio]
    shown_w = min(width, height * frame) / zoom
    shown_h = min(height, width / frame) / zoom
    left, top = (width - shown_w) / 2, (height - shown_h) / 2
    x0, y0, x1, y1 = rect
    box = (
        max(0, round(left + shown_w * x0 / DESIGN_SHORT_SIDE)),
        max(0, round(top + shown_h * y0 / DESIGN_HEIGHT)),
        min(width, round(left + shown_w * x1 / DESIGN_SHORT_SIDE)),
        min(height, round(top + shown_h * y1 / DESIGN_HEIGHT)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    region = grey.crop(box)
    pixels = region.width * region.height
    counted = 0
    for level, count in enumerate(region.histogram()):
        counted += count
        if counted >= pixels * SHARE:
            return level / 255
    return 1.0
