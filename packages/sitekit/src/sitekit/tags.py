"""The advertising tags a page's HTML carries, as far as HTML can say.

Patterns rather than a parser. The tags are pasted snippets with a fixed
shape, and a page cut off at the read limit is not valid HTML anyway.
"""

import re
from typing import Final

# ``fbq('init', '1234567890')`` - the base code Meta hands out.
_PIXEL_INIT: Final = re.compile(r"""fbq\(\s*['"]init['"]\s*,\s*['"](\d{6,20})['"]""")
# The ``<noscript>`` image in the same snippet, with ``&amp;`` or without.
_PIXEL_IMAGE: Final = re.compile(r"""facebook\.com/tr\?[^"'<>\s]*?\bid=(\d{6,20})""")
_TAG_MANAGER: Final = re.compile(r"googletagmanager\.com/(?:gtm\.js|ns\.html)")


def meta_pixel_ids(html: str) -> tuple[str, ...]:
    """Every Meta pixel id in the page, first seen first, each once."""
    found = _PIXEL_INIT.findall(html) + _PIXEL_IMAGE.findall(html)
    return tuple(dict.fromkeys(found))


def has_tag_manager(html: str) -> bool:
    """Whether the page loads Google Tag Manager, which hides other tags."""
    return _TAG_MANAGER.search(html) is not None
