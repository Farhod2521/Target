"""Meta's prose as plain text."""

import re
from html import unescape

_LINK = re.compile(r"<a\b[^>]*>.*?</a\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def plain_text(value: str) -> str:
    """``value`` without markup, entities decoded and spacing collapsed."""
    if "<" not in value and "&" not in value:
        return value.strip()
    stripped = _TAG.sub(" ", _LINK.sub(" ", value))
    return _SPACE.sub(" ", unescape(stripped)).strip()


__all__ = ["plain_text"]
