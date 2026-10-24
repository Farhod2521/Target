"""The font presets a brand picks from, and each as inlined CSS."""

import base64
import io
import logging
from functools import cache
from pathlib import Path
from typing import Final, Literal, get_args

from fontTools import subset
from fontTools.ttLib import TTFont

FontPreset = Literal["bold", "modern", "elegant", "friendly"]
FONT_PRESETS: Final[tuple[FontPreset, ...]] = get_args(FontPreset)
DEFAULT_FONT: Final[FontPreset] = "modern"
FAMILY: Final = "Brand"
_FEATURES: Final[list[str]] = []
_FAMILY_NAME_ID: Final = 1

_FONTS: Final = Path(__file__).parent / "fonts"
logging.getLogger("fontTools").setLevel(logging.WARNING)


def font_file(preset: FontPreset) -> Path:
    """The preset's font file."""
    return _FONTS / preset / "font.woff2"


def font_css(preset: FontPreset = DEFAULT_FONT, *, letters: str = "") -> str:
    """The preset's font as an ``@font-face`` with the file inlined."""
    return _css(preset, needed(letters) if letters else "")


def needed(letters: str) -> str:
    """``letters`` as the set a cut copy keeps: the space, no other
    blank, each letter once, in one order."""
    return "".join(sorted({" "} | {ch for ch in letters if not ch.isspace()}))


@cache
def _css(preset: FontPreset, letters: str) -> str:
    data = _cut(preset, letters) if letters else font_file(preset).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return (
        f"@font-face{{font-family:'{FAMILY}';font-weight:100 900;"
        f"src:url(data:font/woff2;base64,{encoded}) format('woff2')}}"
    )


def _cut(preset: FontPreset, letters: str) -> bytes:
    font = TTFont(font_file(preset))
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = _FEATURES
    options.name_IDs = [_FAMILY_NAME_ID]
    options.notdef_outline = True
    cutter = subset.Subsetter(options)
    cutter.populate(unicodes=[ord(ch) for ch in letters])
    cutter.subset(font)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()
