"""What an ad looks like on one of Meta's surfaces."""

import re
from html import unescape
from typing import Final
from urllib.parse import urlparse

from metaads.client import GraphClient
from metaads.dto_base import MetaDTO
from metaads.errors import MetaAPIError

_BODY: Final = "body"

PREVIEW_SCHEME: Final = "https"
PREVIEW_HOSTS: Final[frozenset[str]] = frozenset(
    {"www.facebook.com", "business.facebook.com"}
)
PREVIEW_PATH: Final = "/ads/api/preview_iframe.php"

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
    """One surface's preview of one ad, or the reason there is none."""
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
    """Meta's ``<iframe>`` markup as an address and a shape."""
    found = _SRC.search(body)
    if not found:
        raise MetaAPIError("the preview answer carried no frame", code=803)

    src = unescape(found.group(1)).strip()
    parsed = urlparse(src)
    if (
        parsed.scheme != PREVIEW_SCHEME
        or parsed.netloc not in PREVIEW_HOSTS
        or parsed.path != PREVIEW_PATH
    ):
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
