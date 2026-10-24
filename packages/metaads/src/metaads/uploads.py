"""Getting the owner's own file to Meta before an ad can point at it.

Two uploads with almost nothing in common.

An **image** goes as multipart when it has a file name, as base64 inside an
ordinary form field when it has none, and either way comes back
identified by its content hash. Uploading the same bytes twice yields the
same hash, which makes the call idempotent for free - a retry costs a
round trip and creates nothing new, so images are never rolled back.

A **video** goes as multipart, comes back with an id, and is not usable
yet. Meta transcodes it, and an ad created against a video still
processing is rejected. That is why :func:`video_status` exists and why the
caller has to wait: there is no way to ask Meta to do it synchronously, and
a fixed sleep is a guess about somebody else's queue.

It also goes as an **open file rather than as bytes**, which the image does
not. A picture is bounded by what Meta accepts at all; a video is bounded
by what somebody filmed on their phone, and a worker holding all of it -
once as bytes and once more as the request body - is how three uploads on
one machine become an out-of-memory kill. The handle is read in pieces by
the transport and nothing keeps them. Above :data:`metaads.chunks.
CHUNKED_ABOVE_BYTES` even one request is too much, and
:mod:`metaads.chunks` sends the same handle as a session instead.

A video can also be sent as a **URL** for Meta to fetch itself, which the
image edge offers no equivalent of. See :func:`upload_video_from_url`.

Neither call is idempotent in the same way, so a retried video upload does
create a second video. That is accepted rather than solved: the alternative
is bookkeeping across task attempts for an object that costs nothing to
leave behind.

And the way back off, which only the owner ever asks for. Nothing in a
launch deletes a file - see :mod:`metaads.assets` - so :func:`delete_image`
and :func:`delete_video` are a person pressing a button on their own
library, after the caller has asked whether any creative still shows it.
"""

import base64
from typing import Any, Final, Protocol

from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.writing import fake_id, graph_client, id_of, redacted


class Readable(Protocol):
    """The part of an open file this package uses, and nothing more.

    A protocol rather than ``BinaryIO`` because of what the caller actually
    holds: a Django ``FieldFile``, a temporary file, a ``BytesIO`` in a
    test. All three read and seek, none of them is the same class, and
    naming a class here would make the package know where its callers keep
    their files.
    """

    def read(self, size: int = ..., /) -> bytes: ...

    def seek(self, offset: int, /) -> int: ...


_IMAGE: Final = "image"
_VIDEO: Final = "video"

# Meta's transcoding states. ``ready`` is the only one an ad may be built
# against; ``error`` is terminal and everything else means keep waiting.
VIDEO_READY: Final = "ready"
VIDEO_ERROR: Final = "error"

# Sent with the multipart body. Meta does not care what it says - it reads
# the container itself - but httpx requires a name for the part.
_VIDEO_FIELD: Final = "source"
_VIDEO_MIME: Final = "application/octet-stream"

# The part a named image travels in, as in Meta's own ``-F filename=@...``
# example. Unlike the video's, the file name on this part matters: it is
# what the ad account's image library calls the row.
_IMAGE_FIELD: Final = "filename"
_IMAGE_MIME: Final = "application/octet-stream"


def upload_image(
    *,
    account_id: str,
    data: bytes,
    token: str,
    filename: str = "",
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Upload one image and return its **hash**.

    Not an id. Meta identifies an image by the hash of its contents and
    everything else by an id, which is the single detail in this package
    most likely to be got wrong by code written from memory - and the
    failure is a creative that builds cleanly and shows nothing.

    ``filename`` names the row in the library. With one, the file goes as
    multipart under that name. Without one it goes as base64 in the
    ``bytes`` field, and Meta calls the row "bytes" - fine for a picture
    fetched from a CDN, wrong for a file the owner named themselves.
    """
    if dry_run:
        return fake_id(_IMAGE)

    with graph_client(client, token) as graph:
        if filename:
            payload = graph.upload(
                f"{account_id}/adimages",
                files={_IMAGE_FIELD: (filename, data, _IMAGE_MIME)},
            )
        else:
            payload = graph.post(
                f"{account_id}/adimages", bytes=base64.b64encode(data).decode("ascii")
            )
    return _hash_of(payload)


def upload_video(
    *,
    account_id: str,
    file: Readable,
    filename: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Upload one video and return its id. Not usable until it is ready.

    One request, so one failure: a transfer that dies at nine tenths sends
    the whole file again, and a file Meta will not take in one body gets an
    empty HTTP 413. Both are what :mod:`metaads.chunks` is for.

    The handle is read from where it stands, so a caller that has already
    read the file hands over a file object seeked to its end and uploads
    nothing.
    """
    if dry_run:
        return fake_id(_VIDEO)

    # ``title`` names the row in the library, as it does at the end of a
    # chunked upload. Without it Meta stores the video untitled, and every
    # later read of the library hands the tile an empty name.
    with graph_client(client, token) as graph:
        payload = graph.upload(
            f"{account_id}/advideos",
            files={_VIDEO_FIELD: (filename, file, _VIDEO_MIME)},
            title=filename,
        )
    return id_of(payload)


def upload_video_from_url(
    *,
    account_id: str,
    file_url: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """The same edge, told where to find the file instead of carrying it.

    ``/act_<id>/advideos`` takes a ``file_url`` and fetches it itself. Its
    sibling ``/act_<id>/adimages`` takes no URL at all - only base64 bytes
    or a copy from another account - which is the asymmetry the whole
    Instagram route is shaped around.

    Worth a second function rather than an optional argument on the one
    above. The two cannot both be given, the failure of passing neither is
    silent, and a signature where two parameters are each conditionally
    required is one nobody reads correctly the second time.

    **Nothing of the file passes through this process.** That is the point:
    a reel Meta fetches directly never occupies a worker, so the size of
    somebody's video stops being our memory problem.

    Not idempotent, exactly like the upload above: a retry creates a second
    video, and that is accepted rather than solved.
    """
    if dry_run:
        return fake_id(_VIDEO)

    with graph_client(client, token) as graph:
        payload = graph.post(f"{account_id}/advideos", file_url=file_url)
    return id_of(payload)


def video_status(
    *, video_id: str, token: str, client: GraphClient | None = None
) -> str:
    """Where Meta has got to with transcoding, lowercased.

    Read defensively: the field is a plain string on some accounts and an
    object with the string inside it on others. An empty answer means Meta
    did not say, which is treated as "still working" rather than as a
    failure.
    """
    with graph_client(client, token) as graph:
        payload = graph.get(video_id, fields="status")

    status = payload.get("status")
    if isinstance(status, dict):
        return str(status.get("video_status", "")).lower()
    return str(status or "").lower()


def video_thumbnail(
    *, video_id: str, token: str, client: GraphClient | None = None
) -> str:
    """A frame Meta picked out, as a URL a creative can carry.

    Only exists once processing has finished. Meta marks one of them
    preferred; when it has not, the first is as good a guess as any and a
    creative without a thumbnail is refused outright.
    """
    with graph_client(client, token) as graph:
        payload = graph.get(f"{video_id}/thumbnails")

    rows = [row for row in payload.get("data", []) if isinstance(row, dict)]
    if not rows:
        return ""

    preferred = next((row for row in rows if row.get("is_preferred")), rows[0])
    return str(preferred.get("uri", ""))


def delete_image(
    *,
    account_id: str,
    image_hash: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> None:
    """Remove one image from the ad account's library, by its hash.

    The edge it was uploaded to, narrowed by the hash it was named by: an
    image has no id, so it has no path of its own to delete.

    Nothing here asks whether an ad still shows the picture. Meta's
    reference says nothing about what happens to one that does, which is
    why the caller reads :func:`metaads.creatives.image_creatives` first
    and refuses rather than finding out.
    """
    if dry_run:
        return

    with graph_client(client, token) as graph:
        payload = graph.delete(f"{account_id}/adimages", hash=image_hash)
    _confirm_deleted(payload, what=_IMAGE)


def delete_video(
    *,
    video_id: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> None:
    """Remove one video. Unlike an image it is an object with an id."""
    if dry_run:
        return

    with graph_client(client, token) as graph:
        payload = graph.delete(video_id)
    _confirm_deleted(payload, what=_VIDEO)


def _confirm_deleted(payload: dict[str, Any], *, what: str) -> None:
    """A delete Meta did not say yes to is not a delete.

    The string form is taken as well as the boolean: refusing a yes over
    its spelling would tell the owner a file is still there when it is
    gone, and the next press would fail on a file that does not exist.
    """
    if payload.get("success") in (True, "true"):
        return
    raise MetaAPIError(
        f"Meta did not confirm the {what} was deleted: {redacted(payload)}"
    )


def _hash_of(payload: dict[str, Any]) -> str:
    """The hash, out of a response keyed by whatever the field was called.

    Meta answers ``{"images": {"<field name>": {"hash": ...}}}`` and the
    field name depends on how the bytes were sent. Reading the first value
    rather than a fixed key is what keeps this working if that ever changes.
    """
    images = payload.get("images")
    if not isinstance(images, dict):
        return ""

    for entry in images.values():
        if isinstance(entry, dict) and entry.get("hash"):
            return str(entry["hash"])

    return ""
