"""How wide a line of text is in a brand's font, and the size it fits at.

A component writes in a box of known width (see ``texts`` in its
manifest). Before anything is rendered, each text is measured with the
font file the renderer will draw it in, and given the largest size from
the box's own down to its smallest at which it fits in the box's lines.
Text that does not fit even at the smallest is a problem the montage is
stopped for (:mod:`videokit.preflight`), never a line cut off on screen.

The measure is Pillow's: the advance of each glyph with the font's
kerning, the same numbers a browser lays the line out by, a few pixels
apart at most. :data:`SLACK` keeps that few pixels on the safe side.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Final

from PIL import ImageFont

from videokit.typefaces import FontPreset, font_file

# Share of a box's width a measured line may take: Pillow and Chromium
# disagree by a pixel or two a word.
SLACK: Final = 0.97
# Sizes are tried this far apart, from the largest down.
STEP_PX: Final = 2


@dataclass(frozen=True, slots=True)
class TextBox:
    """Where one text of a component is written, in design pixels.

    ``gap`` is the space between words in em (``None``: the font's own
    space); ``spacing`` is the letter-spacing in pixels.
    """

    selector: str
    px: int
    min_px: int
    width: int
    lines: int = 1
    spacing: float = 0.0
    gap: float | None = None


@cache
def _font(preset: FontPreset, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file(preset)), px)


def text_width(
    text: str, *, preset: FontPreset, px: int, spacing: float = 0.0
) -> float:
    """How many pixels ``text`` takes on one line."""
    return float(_font(preset, px).getlength(text)) + spacing * len(text)


def lines_needed(text: str, box: TextBox, *, preset: FontPreset, px: int) -> int | None:
    """How many lines ``text`` wraps to at ``px``; None when a single word
    is wider than the box and would be cut."""
    room = box.width * SLACK
    gap = (
        box.gap * px
        if box.gap is not None
        else text_width(" ", preset=preset, px=px, spacing=box.spacing)
    )
    count, used = 0, 0.0
    for word in text.split():
        width = text_width(word, preset=preset, px=px, spacing=box.spacing)
        if width > room:
            return None
        if count and used + gap + width <= room:
            used += gap + width
        else:
            count, used = count + 1, width
    return count


def fitted_px(text: str, box: TextBox, *, preset: FontPreset) -> int | None:
    """The largest size ``text`` fits ``box`` at, or None below its smallest."""
    for px in range(box.px, box.min_px - 1, -STEP_PX):
        needed = lines_needed(text, box, preset=preset, px=px)
        if needed is not None and needed <= box.lines:
            return px
    return None


def fitted_all(texts: Sequence[str], box: TextBox, *, preset: FontPreset) -> int | None:
    """One size for several texts drawn alike (chips, subtitle lines): the
    largest every one of them fits at."""
    sizes = [fitted_px(text, box, preset=preset) for text in texts if text.strip()]
    if any(size is None for size in sizes):
        return None
    return min((s for s in sizes if s is not None), default=box.px)


def packed(
    parts: Sequence[str], box: TextBox, *, preset: FontPreset, joiner: str
) -> tuple[int, tuple[str, ...]] | None:
    """``parts`` on as few lines as they go on, at the largest size.

    A line holds whole parts only - a phone number is never broken - and
    parts that share a line are joined by ``joiner``. Fewer lines win over
    a bigger size: one line at the smallest size beats two at the largest.
    None when some part fits no line, or they need more than ``box.lines``.
    """
    best: tuple[int, tuple[str, ...]] | None = None
    for px in range(box.px, box.min_px - 1, -STEP_PX):
        rows = _rows(parts, box, preset=preset, px=px, joiner=joiner)
        if rows is None or len(rows) > box.lines:
            continue
        if best is None or len(rows) < len(best[1]):
            best = (px, rows)
    return best


def _rows(
    parts: Sequence[str], box: TextBox, *, preset: FontPreset, px: int, joiner: str
) -> tuple[str, ...] | None:
    room = box.width * SLACK
    rows: list[str] = []
    for part in parts:
        if text_width(part, preset=preset, px=px, spacing=box.spacing) > room:
            return None
        joined = f"{rows[-1]}{joiner}{part}" if rows else ""
        if rows and text_width(joined, preset=preset, px=px) <= room:
            rows[-1] = joined
        else:
            rows.append(part)
    return tuple(rows)
