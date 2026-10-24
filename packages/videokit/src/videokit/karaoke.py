"""Subtitles as HTML5 clips whose words light up as they are heard.

Shotstack's own caption asset reads its words from a subtitle file and
places them by itself; here every word carries the time the transcript
gave it, so the highlight is on the word while it is said and nowhere
else. A word stays lit until the next one starts - a gap between two
words is the speaker breathing, not a reason to go dark.

**One clip, many lines.** The brand's font is inlined into the clip, and a
font in every line would outgrow the provider's limit on one edit. So the
lines that share a place on screen go into one clip together (see
:mod:`videokit.edit`), each shown from its start to its stop by the
clip's timeline.

**The brand's colours** (:func:`caption_colors`): words in the brand's
text colour and the word being said in its accent, each only where it
reads against the black outline - the accent is lightened until it does,
then the primary is tried, and a word that still cannot stand apart is
lit by growing alone. A word lit by its colour keeps its size, so the
gaps between words stay even.

The animation is one GSAP timeline, which the renderer seeks frame by
frame: no timers and no clock, so the same line renders the same way
every time.
"""

import json
from collections.abc import Sequence
from html import escape
from typing import Any, Final

from videokit.colors import BLACK, LIGHT, TEXT_CONTRAST, contrast_ratio
from videokit.models import Brand, CaptionLine
from videokit.typefaces import FAMILY, font_css

# Written for a 1080 short side and scaled by the caller. A line that does
# not fit at the size is drawn smaller, never below the smallest.
FONT_PX: Final = 68
MIN_FONT_PX: Final = 44
# The space between two words, as a share of the size: one fixed gap, not
# the font's space, which the renderer widened and narrowed line by line.
WORD_GAP: Final = 0.34
STROKE_PX: Final = 10
# How much a lit word grows - only when no colour sets it apart: growing
# eats into the gap beside it, which reads as two words run together.
LIT_SCALE: Final = 1.1
# How different in lightness the lit word must be from the rest of its
# line. Low, because a change of hue does the rest: yellow on white is
# only 1.4, and reads at once. It rules out a near-white accent.
LIT_APART: Final = 1.3
# Steps toward white when the accent is too dark for the outline.
_LIGHTER: Final = (0.0, 0.15, 0.3, 0.45, 0.6, 0.75)


def caption_colors(brand: Brand) -> tuple[str, str]:
    """The words' colour and the lit word's, from the brand."""
    ink = brand.text if contrast_ratio(brand.text, BLACK) >= TEXT_CONTRAST else LIGHT
    for base in (brand.accent, brand.primary):
        for share in _LIGHTER:
            lit = _toward_white(base, share)
            if (
                contrast_ratio(lit, BLACK) >= TEXT_CONTRAST
                and contrast_ratio(lit, ink) >= LIT_APART
            ):
                return ink, lit
    return ink, ink


def karaoke(
    lines: Sequence[tuple[CaptionLine, float]],
    *,
    brand: Brand,
    font_px: int,
    stroke_px: int,
    places: Sequence[tuple[int, int]] = (),
) -> dict[str, Any]:
    """The ``html5`` asset for ``lines``, each with when it leaves.

    Times in the timeline are relative to the first line's start.
    ``places`` puts each line's middle at its own height in the clip, at
    its own size (pixels): lines moved off the speaker's face share one
    clip - and one copy of the font - wherever each of them sits.
    """
    ink, lit = caption_colors(brand)
    html = "".join(
        f'<div class="l{" sc" if line.scrim else ""}" id="l{row}"'
        + _placed(places[row] if row < len(places) else None)
        + ">"
        + "".join(
            f'<span class="k" id="k{row}_{index}">{escape(word.text)}</span>'
            for index, word in enumerate(line.words)
        )
        + "</div>"
        for row, (line, _) in enumerate(lines)
    )
    css = (
        font_css(
            brand.font,
            letters="".join(word.text for line, _ in lines for word in line.words),
        )
        + "html,body{margin:0;padding:0;overflow:hidden;background:transparent}"
        ".l{position:absolute;left:0;right:0;top:50%;"
        "display:flex;flex-wrap:wrap;justify-content:center;align-items:baseline;"
        f"column-gap:{round(font_px * WORD_GAP)}px;"
        f"text-align:center;font-family:'{FAMILY}',system-ui,sans-serif;"
        f"font-weight:800;font-size:{font_px}px;line-height:1.15;color:{ink};"
        f"paint-order:stroke;-webkit-text-stroke:{stroke_px}px {BLACK};opacity:0}}"
        ".k{display:inline-block}"
        # A line over footage too light for its words sits on a dark backing.
        ".sc{left:50%;right:auto;max-width:100%;"
        "padding:4px 26px;border-radius:22px;background:rgba(0,0,0,.5)}"
    )
    return {
        "type": "html5",
        "html": html,
        "css": css,
        "js": _timeline(lines, ink=ink, lit=lit),
    }


def _placed(place: tuple[int, int] | None) -> str:
    """A line's own height and size, as its style."""
    if place is None:
        return ""
    middle, px = place
    return (
        f' style="top:{middle}px;font-size:{px}px;column-gap:{round(px * WORD_GAP)}px"'
    )


def _timeline(lines: Sequence[tuple[CaptionLine, float]], *, ink: str, lit: str) -> str:
    origin = lines[0][0].start
    grow = LIT_SCALE if lit == ink else 1
    rows = [
        {
            "s": round(line.start - origin, 3),
            "e": round(stop - origin, 3),
            # Every word lit from its start; all but the last go dark when
            # the next one starts.
            "w": [round(word.start - origin, 3) for word in line.words],
        }
        for line, stop in lines
    ]
    # Each line is centred on its height by GSAP's own percentages: a CSS
    # transform would be overwritten by the line's ``y`` tween, and a line
    # on two rows would hang half its height below its band.
    return (
        "gsap.set('.l',{yPercent:-50});gsap.set('.sc',{xPercent:-50});"
        "const tl=gsap.timeline();"
        f"{json.dumps(rows)}.forEach((r,i)=>{{const l='#l'+i;"
        "tl.fromTo(l,{opacity:0,y:24},{opacity:1,y:0,duration:.12,"
        "ease:'power2.out'},r.s);tl.set(l,{opacity:0},r.e);"
        "r.w.forEach((s,j)=>{const w='#k'+i+'_'+j;"
        f"tl.to(w,{{color:'{lit}',scale:{grow},duration:.06}},s);"
        "if(j<r.w.length-1){"
        f"tl.to(w,{{color:'{ink}',scale:1,duration:.06}},r.w[j+1]);}}}});}});"
    )


def _toward_white(color: str, share: float) -> str:
    channels = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(
        f"{round(value + (255 - value) * share):02x}" for value in channels
    )


__all__ = [
    "FONT_PX",
    "MIN_FONT_PX",
    "STROKE_PX",
    "WORD_GAP",
    "caption_colors",
    "karaoke",
]
