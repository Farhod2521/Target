"""Colour arithmetic for a brand: how readable one colour is on another.

The arithmetic itself is :mod:`videokit.colors`, which draws the video with
it; this adds what only the brand form needs.
"""

import re
from typing import Final

from videokit.colors import (
    DARK,
    LIGHT,
    SHAPE_CONTRAST,
    TEXT_CONTRAST,
    contrast_ratio,
    luminance,
    readable_on,
)

__all__ = [
    "DARK",
    "LIGHT",
    "SHAPE_CONTRAST",
    "TEXT_CONTRAST",
    "contrast_ratio",
    "is_hex",
    "is_plain",
    "luminance",
    "readable_on",
]

_HEX: Final = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex(value: str) -> bool:
    """Whether ``value`` is a ``#rrggbb`` colour."""
    return bool(_HEX.match(value))


def is_plain(color: str) -> bool:
    """Near white, near black or grey: a background or an outline, not a brand."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    high, low = max(red, green, blue), min(red, green, blue)
    return (high > 235 and low > 235) or high < 30 or high - low < 24
