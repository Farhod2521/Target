"""Subtitles as HTML5 clips whose words light up as they are heard."""

import json
from collections.abc import Sequence
from html import escape
from typing import Any, Final

from videokit.colors import BLACK, LIGHT, TEXT_CONTRAST, contrast_ratio
from videokit.models import Brand, CaptionLine
from videokit.typefaces import FAMILY, font_css

FONT_PX: Final = 68
MIN_FONT_PX: Final = 44
WORD_GAP: Final = 0.34
STROKE_PX: Final = 10
LIT_SCALE: Final = 1.1
LIT_APART: Final = 1.3
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
    """The ``html5`` asset for ``lines``, each with when it leaves."""
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
            "w": [round(word.start - origin, 3) for word in line.words],
        }
        for line, stop in lines
    ]
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
