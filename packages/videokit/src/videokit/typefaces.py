"""The font presets a brand picks from, and each as inlined CSS.

A preset is one font at one weight (see ``videokit/fonts/README.md``).

**Cut to the clip.** Shotstack refuses an edit over 390 KB and every
HTML5 clip that writes words carries its own copy of the font, so a clip
is given only the letters it writes (:func:`font_css` with ``letters``)
and the space - which is why no component sets its words in capitals
with CSS: a component that wants capitals has its props written so
(``caps`` in its manifest). No layout tables are kept - no kerning,
ligatures or alternates: lines are measured without kerning
(:mod:`videokit.fit` - Pillow here has no shaping engine), so a line
drawn without it is exactly as wide as measured. A cut copy is about a
fifth of the whole file. The
same preset and letters give the same string, built once per process.
"""

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
# The CSS name every component writes its text in.
FAMILY: Final = "Brand"
# Kept in every cut copy: the family's name (which file a clip carries can
# be read back from it).
_FEATURES: Final[list[str]] = []
_FAMILY_NAME_ID: Final = 1

_FONTS: Final = Path(__file__).parent / "fonts"
# fontTools reports every table it cuts at INFO, once per clip.
logging.getLogger("fontTools").setLevel(logging.WARNING)


def font_file(preset: FontPreset) -> Path:
    """The preset's font file."""
    return _FONTS / preset / "font.woff2"


def font_css(preset: FontPreset = DEFAULT_FONT, *, letters: str = "") -> str:
    """The preset's font as an ``@font-face`` with the file inlined.

    With ``letters``, only those and the space are kept; without, the
    whole file.
    """
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
