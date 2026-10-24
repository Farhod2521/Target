"""The rules every component keeps, checked when its folder is read."""

import re
from typing import Final


class ComponentError(ValueError):
    """A component folder that breaks the rules."""


_FORBIDDEN_JS: Final = re.compile(
    r"setTimeout|setInterval|requestAnimationFrame|Date\b|performance\.now"
    r"|fetch\(|XMLHttpRequest|import\(|gsap\.call"
)
_FORBIDDEN_MARKUP: Final = re.compile(
    r"<script|<canvas|<link|<iframe|@import|url\(\s*['\"]?(?!data:)|https?://",
    re.IGNORECASE,
)
_PIXELS_ONLY: Final = re.compile(r"\d(?:em|rem|vh|vw|vmin|vmax)\b")
_CASE_BY_CSS: Final = re.compile(r"text-transform|font-variant", re.IGNORECASE)
_BACKDROP: Final = re.compile(r"backdrop-filter", re.IGNORECASE)


def check(name: str, *, html: str, css: str, js: str) -> None:
    if found := _FORBIDDEN_JS.search(js):
        raise ComponentError(f"{name}: timeline.js uses {found.group(0)!r}")
    for part, text in (
        ("template.html", html),
        ("style.css", css),
        ("timeline.js", js),
    ):
        if found := _FORBIDDEN_MARKUP.search(text):
            raise ComponentError(f"{name}: {part} uses {found.group(0)!r}")
    if found := _PIXELS_ONLY.search(css):
        raise ComponentError(f"{name}: style.css sizes in {found.group(0)!r}, not px")
    if found := _CASE_BY_CSS.search(css):
        raise ComponentError(f"{name}: style.css uses {found.group(0)!r}; see caps")
    for part, text in (("template.html", html), ("style.css", css)):
        if found := _BACKDROP.search(text):
            raise ComponentError(f"{name}: {part} uses {found.group(0)!r}")
