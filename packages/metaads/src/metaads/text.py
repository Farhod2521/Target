"""Meta's prose as plain text.

Some of the sentences Meta writes for an advertiser arrive as HTML: an
issue on an object that cannot deliver says ``can&#039;t``, breaks its
lines with ``<br />`` and ends in ``<a href="...">See Details</a>``. Every
screen in a caller prints text, so markup kept here reaches a person as
entities and tags.

The link goes with its tag. Its words alone - "See Details" - promise
something the sentence no longer carries.
"""

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
