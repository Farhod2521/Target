"""Subtitles over the footage, and the band they sit in.

**Word by word** when the spec carries the words' times, in the brand's
font and colours: one HTML5 clip per run of lines that sit in the same
band (see :mod:`videokit.karaoke`). Otherwise the SRT file goes to
Shotstack's own caption asset, in the provider's font, which knows only
when a line starts.

The band is ``SUBTITLES``, a little narrower than the frame, and
``SUBTITLES_LOW`` while the footage is split for a panel.
"""

from typing import Any, Final

from videokit.colors import BLACK
from videokit.fit import TextBox, fitted_all
from videokit.karaoke import (
    FONT_PX,
    MIN_FONT_PX,
    STROKE_PX,
    WORD_GAP,
    caption_colors,
    karaoke,
)
from videokit.layout import (
    DESIGN_SHORT_SIDE,
    SAFE_RIGHT_PX,
    ZONES,
    band_box,
    frame_size,
    safe_area,
    scaled,
    zone_box,
)
from videokit.models import CaptionLine, EditSpec

# How much of the frame's width a block of text may take. A narrow frame
# gives most of its width; a wide one less, so a sentence does not run
# edge to edge.
_TEXT_SHARE: Final = 0.86
_WIDE_TEXT_SHARE: Final = 0.6
# A line stays a moment after its last word, unless the next one is due.
_CAPTION_TAIL: Final = 0.15
# A subtitle line wraps to two rows at most.
CAPTION_ROWS: Final = 2
# A lit word may grow (LIT_SCALE); the measure leaves it room.
_LIT_ROOM: Final = 0.94


def text_width(spec: EditSpec) -> int:
    """How wide a block of text may be, in the frame's pixels.

    On a vertical frame, as wide as the frame less the apps' button column
    on both sides, so the line stays centred and clear of it.
    """
    width, height = frame_size(spec.resolution, spec.aspect_ratio)
    if safe_area(spec.aspect_ratio) is not None:
        return width - 2 * scaled(SAFE_RIGHT_PX, spec.resolution)
    return round(width * (_TEXT_SHARE if width <= height else _WIDE_TEXT_SHARE))


def caption_box(spec: EditSpec) -> TextBox:
    """The box one subtitle line is measured in, in design pixels."""
    short = min(frame_size(spec.resolution, spec.aspect_ratio))
    design = text_width(spec) * DESIGN_SHORT_SIDE / short
    return TextBox(
        selector=".l",
        px=FONT_PX,
        min_px=MIN_FONT_PX,
        width=round(design * _LIT_ROOM),
        lines=CAPTION_ROWS,
        gap=WORD_GAP,
    )


def caption_px(spec: EditSpec) -> int | None:
    """One size for every subtitle line: the largest all of them fit at,
    two rows each. None when some line does not fit even at the smallest."""
    texts = [" ".join(word.text for word in line.words) for line in spec.captions]
    return fitted_all(texts, caption_box(spec), preset=spec.brand.font)


def _split_at(spec: EditSpec, at: float) -> bool:
    """Whether the footage is moved down for a panel at ``at``."""
    return any(
        span.layout == "split_top" and span.start <= at < span.end
        for span in spec.layouts
    )


def _caption_box(spec: EditSpec, *, low: bool = False) -> dict[str, Any]:
    """The subtitles' own band, a little narrower than the frame.

    Lower while the footage is split - see ``SUBTITLES_LOW``.
    """
    return {
        **zone_box(
            "SUBTITLES_LOW" if low else "SUBTITLES",
            spec.resolution,
            spec.aspect_ratio,
        ),
        "width": text_width(spec),
    }


def word_clips(spec: EditSpec) -> list[dict[str, Any]]:
    """The subtitles, all lines in one clip.

    The brand's font goes into the clip, and a font in every line would
    outgrow the provider's limit on one edit. So one clip covers every
    band a line sits in - over the mouth, under the chin while the footage
    is split, or wherever a line was moved off the speaker's face
    (``CaptionLine.top``) - and each line is drawn at its own height and
    size inside it.
    """
    if not spec.captions:
        return []
    every = caption_px(spec) or MIN_FONT_PX
    stroke_px = max(1, scaled(STROKE_PX, spec.resolution))
    lines = spec.captions
    timed: list[tuple[CaptionLine, float]] = []
    bands: list[tuple[int, int, int]] = []
    for line, after in zip(lines, [*lines[1:], None], strict=True):
        stop = line.end + _CAPTION_TAIL
        if after is not None:
            stop = min(stop, after.start)
        stop = max(stop, line.start + 0.1)
        timed.append((line, stop))
        if line.top is not None and line.bottom is not None:
            top, bottom = line.top, line.bottom
        else:
            low = _split_at(spec, (line.start + line.end) / 2)
            top, bottom = ZONES["SUBTITLES_LOW" if low else "SUBTITLES"]
        bands.append((top, bottom, line.px or every))
    canvas_top = min(b[0] for b in bands)
    canvas_bottom = max(b[1] for b in bands)
    places = [
        (
            scaled((top + bottom) / 2 - canvas_top, spec.resolution),
            scaled(px, spec.resolution),
        )
        for top, bottom, px in bands
    ]
    start = timed[0][0].start
    return [
        {
            "asset": karaoke(
                timed,
                brand=spec.brand,
                font_px=scaled(every, spec.resolution),
                stroke_px=stroke_px,
                places=places,
            ),
            "start": round(start, 3),
            "length": round(timed[-1][1] - start, 3),
            **band_box(canvas_top, canvas_bottom, spec.resolution, spec.aspect_ratio),
            "width": text_width(spec),
        }
    ]


def srt_clip(spec: EditSpec, *, font: str) -> dict[str, Any]:
    """Subtitles from the SRT file, in the provider's own font: the
    fallback when the words' times are missing or do not fit."""
    size = scaled(FONT_PX, spec.resolution)
    ink, lit = caption_colors(spec.brand)
    return {
        "asset": {
            "type": "rich-caption",
            "src": spec.captions_url,
            "font": {"family": font, "size": size, "color": ink, "weight": 800},
            "stroke": {
                "width": max(1, scaled(STROKE_PX / 2, spec.resolution)),
                "color": BLACK,
                "opacity": 1,
            },
            "animation": {"style": "highlight"},
            "active": {"font": {"color": lit}},
        },
        "start": 0,
        "length": "end",
        **_caption_box(spec),
    }
