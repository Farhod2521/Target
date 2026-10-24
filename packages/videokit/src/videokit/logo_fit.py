"""How big a logo must be drawn for its lettering to read, and whether it
sits whole on its plate.

A logo arrives as a small PNG (a data URI, a few hundred pixels wide):
on its own, or on the light or dark plate made for footage it would be
lost on (:func:`videokit.images.badge`). Read once per copy:

- **its lettering** - the letters are found as a row of three or more
  shapes of one height side by side; the tallest such row is the name,
  and its height as a share of the copy's is what decides how tall the
  copy must be drawn for the name to be :data:`MIN_TEXT_PX` tall;
- **the plate** - every pixel of the logo must lie inside the plate with
  :data:`PLATE_MARGIN` of plate around it. A plate that cuts into the
  mark is a broken logo.

The sizes each place draws a logo at (:func:`corner_size`,
:func:`name_bar_logo`, :func:`drawn_size` on the closing card) grow until
the name reads, up to the place's own limit; past it the place does
without (the corner) or writes the name in letters instead (the name bar,
the closing card).
"""

import base64
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

import cv2
import numpy as np

# The smallest the lettering of a logo may be drawn, for a 1080 short side.
MIN_TEXT_PX: Final = 24
# Plate kept clear around the logo, as a share of the plate's short side.
PLATE_MARGIN: Final = 0.06
# A colour within this distance (sum over RGB) of the plate's is the plate.
_PLATE_NEAR: Final = 90
# A plate fills nearly its whole picture (all but its rounded corners)
# and its colour covers at least this much of what is opaque.
_PLATE_FILL: Final = 0.8
_PLATE_SHARE: Final = 0.35
_ROW_MIN: Final = 3

# Where each place draws a logo: its smallest height, its largest height
# and width.
CORNER_HEIGHT: Final = (90, 160)
CORNER_MAX_WIDTH: Final = 480
# A copy that cannot be read here is drawn in the corner's old box.
UNMEASURED_CORNER: Final = (220, 110)
NAME_BAR_HEIGHT: Final = (100, 150)
NAME_BAR_MAX_WIDTH: Final = 620
# The closing card's logo: large when it stands for the name, smaller
# when the name is written under it.
CARD_MAX: Final = (820, 400)
CARD_WITH_NAME: Final = (600, 240)


@dataclass(frozen=True, slots=True)
class LogoCopy:
    """What one copy of a logo is, as drawn."""

    width: int
    height: int
    # The name's letters' height over the copy's height; None: no lettering.
    text_share: float | None
    # Whether the logo sits whole on its plate (always, with no plate).
    on_plate_whole: bool

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0

    def needed_height(self) -> int:
        """How tall it must be drawn for its lettering to read."""
        if not self.text_share:
            return 0
        return math.ceil(MIN_TEXT_PX / self.text_share)

    def text_px(self, height: float) -> float | None:
        """How tall its lettering is when drawn ``height`` tall."""
        return None if not self.text_share else self.text_share * height


@lru_cache(maxsize=64)
def logo_copy(uri: str) -> LogoCopy | None:
    """``uri`` read; None when it is not a picture."""
    if "," not in uri:
        return None
    raw = np.frombuffer(base64.b64decode(uri.split(",", 1)[1]), np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    opaque = image[:, :, 3] > 128
    colour = image[:, :, :3].astype(np.int32)
    plate = _plate(colour, opaque)
    if plate is None:
        drawn = opaque
    else:
        drawn = opaque & (np.abs(colour - plate).sum(axis=2) > _PLATE_NEAR)
    height, width = opaque.shape
    return LogoCopy(
        width=width,
        height=height,
        text_share=_text_share(drawn),
        on_plate_whole=plate is None or _whole(drawn, opaque),
    )


def corner_size(uri: str) -> tuple[int, int] | None:
    """Width and height of the corner logo; None when it cannot read there."""
    copy = logo_copy(uri)
    low, high = CORNER_HEIGHT
    if copy is None:
        return UNMEASURED_CORNER
    height = max(low, copy.needed_height())
    if height > high or height * copy.aspect > CORNER_MAX_WIDTH:
        return None
    return round(height * copy.aspect), height


def name_bar_logo(uri: str) -> int | None:
    """How tall the logo is drawn in place of the name; None when its
    lettering cannot read there and the name is written instead."""
    copy = logo_copy(uri)
    low, high = NAME_BAR_HEIGHT
    if copy is None:
        # Not a picture this can read - nor anything to measure; drawn as
        # it always was.
        return low
    height = max(low, copy.needed_height())
    if height > high or height * copy.aspect > NAME_BAR_MAX_WIDTH:
        return None
    return height


def drawn_size(uri: str, box: tuple[int, int]) -> tuple[int, int] | None:
    """Width and height of the copy fitted inside ``box``, kept in shape."""
    copy = logo_copy(uri)
    if copy is None:
        return box
    width, height = box
    drawn = min(height, width / copy.aspect)
    return round(drawn * copy.aspect), round(drawn)


def reads_at(uri: str, height: float) -> bool:
    """Whether the copy's lettering, if any, reads drawn ``height`` tall."""
    copy = logo_copy(uri)
    if copy is None:
        return True
    px = copy.text_px(height)
    return px is None or px >= MIN_TEXT_PX


def _plate(colour: np.ndarray, opaque: np.ndarray) -> np.ndarray | None:
    """The plate's colour, when the copy is a logo on a plate."""
    corners = (opaque[0, 0], opaque[0, -1], opaque[-1, 0], opaque[-1, -1])
    if any(corners) or opaque.mean() < _PLATE_FILL:
        return None
    shown = colour[opaque] // 16
    values, counts = np.unique(shown, axis=0, return_counts=True)
    if counts.max() < _PLATE_SHARE * len(shown):
        return None
    return values[counts.argmax()] * 16 + 8  # type: ignore[no-any-return]


def _whole(drawn: np.ndarray, opaque: np.ndarray) -> bool:
    """Whether every drawn pixel has plate around it."""
    margin = max(2, round(min(opaque.shape) * PLATE_MARGIN))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * margin + 1, 2 * margin + 1)
    )
    inner = cv2.erode(opaque.astype(np.uint8), kernel) > 0
    return bool(not (drawn & ~inner).any())


def _text_share(drawn: np.ndarray) -> float | None:
    """The tallest row of letters over the copy's height."""
    count, _labels, stats, _centres = cv2.connectedComponentsWithStats(
        drawn.astype(np.uint8), connectivity=8
    )
    height = drawn.shape[0]
    shapes = [
        (int(stats[i][1]), int(stats[i][3]))
        for i in range(1, count)
        if stats[i][4] > 3 and stats[i][3] < 0.6 * height
    ]
    rows: list[list[tuple[int, int]]] = []
    for top, tall in sorted(shapes):
        middle = top + tall / 2
        for row in rows:
            size = float(np.median([t for _y, t in row]))
            centre = float(np.median([y + t / 2 for y, t in row]))
            if abs(middle - centre) < 0.6 * size and 0.5 < tall / size < 2:
                row.append((top, tall))
                break
        else:
            rows.append([(top, tall)])
    letters = [row for row in rows if len(row) >= _ROW_MIN]
    if not letters:
        return None
    return max(float(np.median([t for _y, t in row])) for row in letters) / height
