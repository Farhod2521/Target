"""The file itself, from the CDN Meta serves it on."""

from typing import Final
from urllib.parse import urlsplit

import httpx

from metaads.client import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
from metaads.dto_base import MetaDTO
from metaads.errors import MetaError, MetaTemporaryError

FETCH_TIMEOUT_SECONDS: Final = 60.0


class MediaUnavailableError(MetaError):
    """The CDN would not hand the file over."""


class MediaTooLargeError(MetaError):
    """Bigger than the caller said it could hold."""


class MediaProbe(MetaDTO):
    """Whether this file could be fetched, without fetching it.

    No URL is echoed back. The console already answers with the raw media
    row, ``media_url`` included, and repeating a signed link in a second
    place is a habit worth not forming.

    ``reachable`` is about the round trip, not about the answer: a 403 is
    reachable and is a refusal, and telling those apart is the entire
    purpose of the call.
    """

    reachable: bool
    status: int = 0
    content_type: str = ""
    content_length: int = 0
    host: str = ""
    detail: str = ""


def probe_media(*, url: str, client: httpx.Client | None = None) -> MediaProbe:
    """Ask the CDN for the file and read only the headers."""
    graph = client or _client()
    host = urlsplit(url).netloc

    try:
        with graph.stream("GET", url) as response:
            return MediaProbe(
                reachable=True,
                status=response.status_code,
                content_type=response.headers.get("content-type", ""),
                content_length=_length(response.headers.get("content-length")),
                host=host,
            )
    except httpx.HTTPError as exc:
        return MediaProbe(reachable=False, host=host, detail=str(exc))
    finally:
        if client is None:
            graph.close()


def download_media(
    *, url: str, max_bytes: int, client: httpx.Client | None = None
) -> bytes:
    """The file, in memory, or a refusal before it gets there."""
    graph = client or _client()
    try:
        with graph.stream("GET", url) as response:
            _refuse_status(response.status_code)
            declared = _length(response.headers.get("content-length"))
            if declared > max_bytes:
                raise MediaTooLargeError(
                    f"media is {declared} bytes, ceiling is {max_bytes}"
                )

            chunks: list[bytes] = []
            held = 0
            for chunk in response.iter_bytes():
                held += len(chunk)
                if held > max_bytes:
                    raise MediaTooLargeError(
                        f"media exceeded the {max_bytes} byte ceiling while reading"
                    )
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise MetaTemporaryError(f"could not reach the media CDN: {exc}") from exc
    finally:
        if client is None:
            graph.close()

    return b"".join(chunks)


def _refuse_status(status: int) -> None:
    """A 403 here is nearly always a signed URL that has expired."""
    if status >= 500:
        raise MetaTemporaryError(f"media CDN answered {status}")
    if status != httpx.codes.OK:
        raise MediaUnavailableError(f"media CDN answered {status}")


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_SECONDS,
            read=FETCH_TIMEOUT_SECONDS,
            write=READ_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        ),
        follow_redirects=True,
    )


def _length(value: str | None) -> int:
    """Absent or unparseable is zero, which reads as "the CDN did not say"."""
    try:
        return int(value or 0)
    except ValueError:
        return 0
