"""What an ad looks like on one of Meta's surfaces.

Read-only, and one call: ``GET /{object_id}/previews?ad_format=<SURFACE>``.
The same edge exists on an ad and on the creative behind it, so the caller
passes whichever id it holds and this module does not care which.

**Meta answers with markup, not with an address.** The one field on the
node is ``body``, and it holds a whole ``<iframe>`` element - the address,
a width, a height and an inline style. The address is what is worth
having; the rest is Meta's opinion about how big a frame should be, formed
without knowing whose screen it is going on.

So this module's real work is the parse, and the parse has three traps in
it. All three are documented here because none of them is documented by
Meta:

* **The address is HTML-escaped.** ``&`` arrives as ``&amp;``, which means
  the signing token ``t`` is part of the previous parameter's value unless
  somebody unescapes it. Meta then answers the frame with "The parameter t
  is required" - a failure that happens in the visitor's browser, on the
  far side of every log this project has.
* **The address is signed and perishable.** Both query parameters are
  opaque and Meta publishes no lifetime for them. Nothing here caches, and
  the caller is expected to treat what it stores as going stale.
* **The host is not the documented one.** Meta's reference shows
  ``www.facebook.com``; a live ad account answers every preview with
  ``business.facebook.com``, and there is no published rule for which it
  picks. Both are allowed below - see ``PREVIEW_HOSTS``.

Which surfaces exist is Meta's list and it is long - seventy-odd values,
from ``MOBILE_FEED_STANDARD`` to ``WHATSAPP_STATUS_MEDIA``. It is not
enumerated here: this package would have to be released every time Meta
adds a placement, and the caller has to pass a string either way. Meta
also supports only certain pairings of creative and surface and refuses
the rest with error 100, so an unsupported pairing raises rather than
answering blank.
"""

import re
from html import unescape
from typing import Final
from urllib.parse import urlparse

from metaads.client import GraphClient
from metaads.dto_base import MetaDTO
from metaads.errors import MetaAPIError

# The one field the AdPreview node has.
_BODY: Final = "body"

# Where a legitimate preview frame points, and nowhere else.
#
# **An allowlist, because this address ends up in an ``iframe`` on a
# customer's screen.** Everything above this package escapes what it
# renders and none of it can help here: the value *is* a URL and it is
# going into an attribute that will be followed. What protects that
# attribute is knowing which host is allowed to be in it, and the only
# layer that knows Meta's is this one.
#
# Scheme included on purpose. A ``javascript:`` address parses with an
# empty netloc, which would pass a host check written as "not somebody
# else's domain" - the check has to be "is exactly this one".
#
# **Two hosts.** Meta's documented example uses ``www.facebook.com``; a
# live account answers every single preview with ``business.facebook.com``
# instead, and Meta publishes no rule for which it picks. With one host in
# this set the parse refuses every frame - and the refusal is a log line,
# so the preview is quietly empty rather than visibly broken.
#
# A set rather than a suffix check. "Ends with facebook.com" is a rule
# that ``evil-facebook.com`` and ``facebook.com.attacker.net`` both pass,
# and there is nothing to gain by being clever about a list of two.
PREVIEW_SCHEME: Final = "https"
PREVIEW_HOSTS: Final[frozenset[str]] = frozenset(
    {"www.facebook.com", "business.facebook.com"}
)
PREVIEW_PATH: Final = "/ads/api/preview_iframe.php"

# ``src="..."`` out of the element Meta sends. A regex rather than an HTML
# parser: the payload is one tag with no nesting and no siblings, and the
# thing being extracted is a quoted attribute value. Non-greedy up to the
# closing quote, so an address containing an escaped quote ends the match
# where the attribute ends rather than where the tag does.
_SRC = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_WIDTH = re.compile(r"""\bwidth\s*=\s*["']?(\d+)""", re.IGNORECASE)
_HEIGHT = re.compile(r"""\bheight\s*=\s*["']?(\d+)""", re.IGNORECASE)


class PreviewFrame(MetaDTO):
    """One preview, reduced to what can safely be rendered.

    ``width`` and ``height`` are Meta's suggestion and are nought when the
    element carried neither. Kept because an aspect ratio is the one thing
    a caller cannot work out for itself - a story frame is portrait and a
    feed frame is not - and dropped from the markup that gets rendered,
    because the width of a card on a phone is the phone's business.
    """

    src: str
    width: int = 0
    height: int = 0


def get_preview(
    *,
    object_id: str,
    ad_format: str,
    token: str,
    client: GraphClient | None = None,
) -> PreviewFrame:
    """One surface's preview of one ad, or the reason there is none.

    ``object_id`` is an ad id or a creative id; the edge is the same on
    both and Meta decides which it was handed.

    Raises :class:`~metaads.errors.MetaAPIError` when the answer holds no
    frame this module is willing to hand on - an empty list, markup with
    no address in it, or an address pointing somewhere other than Meta's
    own preview host. All three are the same thing to a caller: no
    preview. Raising rather than returning an empty frame, because an
    empty ``src`` rendered into an ``iframe`` is a blank box with no
    explanation, and every failure here has one.
    """
    graph = client or GraphClient(token=token)
    try:
        payload = graph.get(f"{object_id}/previews", ad_format=ad_format)
    finally:
        if client is None:
            graph.close()

    rows = payload.get("data") or []
    body = rows[0].get(_BODY, "") if rows and isinstance(rows[0], dict) else ""
    return frame_of(str(body))


def frame_of(body: str) -> PreviewFrame:
    """Meta's ``<iframe>`` markup as an address and a shape.

    Separate from the call so the parse can be tested against the exact
    strings Meta's own reference publishes, without a transport in the
    way - and so the two traps in the module docstring have one place to
    be got right.
    """
    found = _SRC.search(body)
    if not found:
        raise MetaAPIError("the preview answer carried no frame", code=803)

    # Before anything else looks at it. ``&amp;`` in the address is what
    # separates a working frame from "The parameter t is required", and
    # every check below would pass on the escaped form as readily as on
    # the real one.
    src = unescape(found.group(1)).strip()
    parsed = urlparse(src)
    if (
        parsed.scheme != PREVIEW_SCHEME
        or parsed.netloc not in PREVIEW_HOSTS
        or parsed.path != PREVIEW_PATH
    ):
        # Deliberately says nothing about what the address was. It is
        # somebody else's content and this message reaches a log.
        raise MetaAPIError("the preview frame pointed somewhere unexpected", code=803)

    return PreviewFrame(
        src=src, width=_number(_WIDTH, body), height=_number(_HEIGHT, body)
    )


def _number(pattern: re.Pattern[str], body: str) -> int:
    """One of Meta's size attributes, or nought for "it did not say"."""
    found = pattern.search(body)
    return int(found.group(1)) if found else 0


__all__ = [
    "PREVIEW_HOSTS",
    "PREVIEW_PATH",
    "PREVIEW_SCHEME",
    "PreviewFrame",
    "frame_of",
    "get_preview",
]
