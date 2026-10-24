"""A page's brand made whole for a montage, and an SVG logo made safe.

**Gaps.** What the brand leaves empty is filled when a montage is made:
the page's name for the brand's, the logo's own colour for the primary,
a neutral palette for the rest.

**SVG.** A logo drawn as SVG is markup, and markup can carry scripts,
event handlers and links that reach out. What is kept is drawing only -
shapes, paths, gradients, text - by an allowlist of elements and
attributes; anything else is dropped, and a file that declares entities
is refused outright rather than parsed.
"""

import re
import xml.etree.ElementTree as ET
from typing import Final

from videokit import Brand
from videokit.typefaces import DEFAULT_FONT, FONT_PRESETS

from core.montage.errors import MontageError

# A neutral palette for a kit with nothing in it: dark slate, warm yellow.
NEUTRAL_PRIMARY: Final = "#1e293b"
NEUTRAL_ACCENT: Final = "#facc15"
NEUTRAL_TEXT: Final = "#ffffff"

_SVG_NS: Final = "http://www.w3.org/2000/svg"
_ELEMENTS: Final = frozenset(
    {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
     "polygon", "defs", "linearGradient", "radialGradient", "stop", "clipPath",
     "mask", "title", "desc", "text", "tspan"}
)  # fmt: skip
_ATTRIBUTES: Final = frozenset(
    {"id", "class", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2",
     "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "fill-opacity",
     "fill-rule", "clip-rule", "stroke", "stroke-width", "stroke-linecap",
     "stroke-linejoin", "stroke-miterlimit", "stroke-opacity", "opacity",
     "transform", "offset", "stop-color", "stop-opacity", "gradientUnits",
     "gradientTransform", "clip-path", "mask", "font-size", "font-weight",
     "font-family", "text-anchor", "preserveAspectRatio", "style"}
)  # fmt: skip
# A reference may only point inside the file.
_OUTSIDE: Final = re.compile(
    r"url\(\s*['\"]?(?!#)|expression|@import|javascript:", re.I
)


class BrandFileError(MontageError):
    """A logo that cannot be used."""


def resolved(
    *,
    primary: str,
    accent: str,
    text: str,
    name: str,
    page_name: str,
    tagline: str,
    cta_text: str,
    telegram: str,
    instagram: str,
    cta_phone: str,
    logo: str,
    logo_color: str,
    font: str = DEFAULT_FONT,
) -> Brand:
    """The brand with every gap filled: what a montage is made with.

    The handle shown is Telegram's when there is one, else Instagram's;
    a font that is not a preset is the default one.
    """
    return Brand(
        primary=primary or logo_color or NEUTRAL_PRIMARY,
        accent=accent or NEUTRAL_ACCENT,
        text=text or NEUTRAL_TEXT,
        name=(name or page_name)[:60],
        tagline=tagline,
        cta_text=cta_text,
        cta_handle=f"@{telegram or instagram}" if telegram or instagram else "",
        cta_phone=cta_phone,
        logo=logo,
        font=next((f for f in FONT_PRESETS if f == font), DEFAULT_FONT),
    )


def clean_svg(data: bytes) -> bytes:
    """The SVG with drawing only left in it. ``BrandFileError`` if unusable."""
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise BrandFileError("svg declares a doctype or entities")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise BrandFileError("svg does not parse") from exc
    if _local(root.tag) != "svg":
        raise BrandFileError("not an svg")
    _prune(root)
    ET.register_namespace("", _SVG_NS)
    return bytes(ET.tostring(root, encoding="utf-8"))


def _prune(element: ET.Element) -> None:
    for child in list(element):
        if _local(child.tag) not in _ELEMENTS:
            element.remove(child)
            continue
        _prune(child)
    for key in list(element.attrib):
        value = element.attrib[key]
        if _local(key) not in _ATTRIBUTES or _OUTSIDE.search(value):
            del element.attrib[key]


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]
