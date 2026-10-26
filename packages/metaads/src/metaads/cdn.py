"""The file itself, from the CDN Meta serves it on.

Apart from every other module here because it is not a Graph call. There is
no version, no token, no ``X-Business-Use-Case-Usage`` header and no error
envelope - just a signed URL that answers with bytes or does not.

It exists because of one asymmetry in Meta's own API. An Instagram post's
file is a ``media_url``; ``/act_<id>/adimages`` accepts base64 ``bytes`` or
``copy_from`` and **no URL of any kind**. So the only route from a post to
an ad creative runs through our own network: fetch, then upload.

Nothing here is stored. The bytes go from this module to Meta and are
forgotten, which is deliberate - a signed URL expires, and a copy of
somebody's photograph on our disk is a copy we would then have to look
after.

One thing no documentation says: the CDN converts on delivery. A post
whose URL ends ``.heic`` or ``.webp`` answers
with ``Content-Type: image/jpeg``, because ``stp=dst-jpg`` in the query
tells it to. So nothing here converts anything - the extension is a name
and the header is the fact.

Nor does anything here pretend to be a browser. httpx names itself in the
``User-Agent`` and the CDN answers 200.
"""

from typing import Final
from urllib.parse import urlsplit

import httpx

from metaads.client import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS
from metaads.dto_base import MetaDTO
from metaads.errors import MetaError, MetaTemporaryError

# Long enough for a video on a slow origin, short enough that a worker is
# not held by a CDN that has stopped answering. Deliberately below the
# upload timeout next door: fetching is the cheap half.
FETCH_TIMEOUT_SECONDS: Final = 60.0


class MediaUnavailableError(MetaError):
    """The CDN would not hand the file over.

    Its own class rather than one of Meta's API errors, because no Graph
    endpoint was called and there is no code to log. Nearly always a signed
    URL that has aged out, which is why nothing stores one.
    """


class MediaTooLargeError(MetaError):
    """Bigger than the caller said it could hold.

    Ours, not Meta's. The file is fine and the ad account would take it -
    this is a worker declining to keep tens of megabytes in memory on
    somebody's behalf.
    """


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
    """Ask the CDN for the file and read only the headers.

    Streamed and abandoned rather than downloaded: the questions are
    whether our own network reaches this host at all, what it calls the
    file, and how big it is - and none of them need a body. A reel is tens
    of megabytes, and a diagnostic that pulled one down every time it was
    pressed would be measuring our patience rather than Meta's CDN.

    No browser is imitated. httpx names itself in the ``User-Agent`` and
    stays that way; if the CDN turns out to refuse that, the answer here
    says so and pretending otherwise becomes a decision somebody makes
    rather than a line that arrived with the first draft.

    A transport failure is an answer, not an exception. The caller is a
    console printing what happened, and "connection refused" is exactly
    what it opened the page to read.
    """
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
    """The file, in memory, or a refusal before it gets there.

    ``max_bytes`` has no default, which is deliberate. This package cannot
    know how much memory the caller can spare: the same function feeds a
    photograph of a third of a megabyte and, if the URL upload ever stops
    working, a reel of tens. A default here would be a guess made in the
    wrong module and inherited silently by every caller after the first.

    The ceiling is checked **twice**, and the second check is not
    belt-and-braces. ``Content-Length`` is what the header says and a
    chunked response carries none at all - so a reader that trusted it
    would let through exactly the file it exists to stop.

    A refusal by the CDN is permanent for this attempt and a 5xx is not,
    which is the whole reason they are different classes: the caller's
    Celery task reads ``retryable`` and nothing else.
    """
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
        # A timeout, a reset, a DNS failure. None of them say anything about
        # the file, so the next attempt is worth making.
        raise MetaTemporaryError(f"could not reach the media CDN: {exc}") from exc
    finally:
        if client is None:
            graph.close()

    return b"".join(chunks)


def _refuse_status(status: int) -> None:
    """A 403 here is nearly always a signed URL that has expired.

    Which is why ``media_url`` is read again immediately before this is
    called, and never stored: the fix is a fresh address, not a retry of
    the old one.
    """
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
    """Absent or unparseable is zero, which reads as "the CDN did not say".

    Chunked responses carry no length at all, so zero has to mean unknown
    rather than empty - a ceiling that treated it as empty would let
    exactly the files it exists to stop straight through.
    """
    try:
        return int(value or 0)
    except ValueError:
        return 0
