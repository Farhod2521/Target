"""Colour arithmetic: how readable one colour is on another.

Contrast is WCAG 2's ratio (1 to 21) from relative luminance, with the
sRGB curve undone first. Text needs :data:`TEXT_CONTRAST`; a logo or an
icon, which is bigger and not read letter by letter, needs
:data:`SHAPE_CONTRAST`.
"""

from typing import Final

TEXT_CONTRAST: Final = 4.5
SHAPE_CONTRAST: Final = 3.0
DARK: Final = "#111111"
LIGHT: Final = "#ffffff"
BLACK: Final = "#000000"


def luminance(color: str) -> float:
    """WCAG relative luminance of ``#rrggbb``, 0 (black) to 1 (white)."""
    red, green, blue = (_linear(int(color[i : i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast between two ``#rrggbb`` colours, 1 to 21."""
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def readable_on(background: str) -> str:
    """:data:`DARK` or :data:`LIGHT`, whichever reads better on ``background``."""
    if contrast_ratio(DARK, background) >= contrast_ratio(LIGHT, background):
        return DARK
    return LIGHT


def is_dark(color: str) -> bool:
    """Whether light text reads better on ``color`` than dark text does."""
    return readable_on(color) == LIGHT


def shade(color: str, *, share: float) -> str:
    """``color`` with ``share`` of it mixed into black: 0.4 is much darker."""
    channels = (round(int(color[i : i + 2], 16) * share) for i in (1, 3, 5))
    return "#" + "".join(f"{value:02x}" for value in channels)


def _linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)
