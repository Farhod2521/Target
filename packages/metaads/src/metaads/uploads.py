"""Getting the owner's own file to Meta before an ad can point at it."""

import base64
from typing import Any, Final, Protocol

from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.writing import fake_id, graph_client, id_of, redacted


class Readable(Protocol):
    """The part of an open file this package uses, and nothing more."""

    def read(self, size: int = ..., /) -> bytes: ...

    def seek(self, offset: int, /) -> int: ...


_IMAGE: Final = "image"
_VIDEO: Final = "video"

VIDEO_READY: Final = "ready"
VIDEO_ERROR: Final = "error"

_VIDEO_FIELD: Final = "source"
_VIDEO_MIME: Final = "application/octet-stream"

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
    """Upload one image and return its **hash**."""
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
    """Upload one video and return its id. Not usable until it is ready."""
    if dry_run:
        return fake_id(_VIDEO)

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
    """The same edge, told where to find the file instead of carrying it."""
    if dry_run:
        return fake_id(_VIDEO)

    with graph_client(client, token) as graph:
        payload = graph.post(f"{account_id}/advideos", file_url=file_url)
    return id_of(payload)


def video_status(
    *, video_id: str, token: str, client: GraphClient | None = None
) -> str:
    """Where Meta has got to with transcoding, lowercased."""
    with graph_client(client, token) as graph:
        payload = graph.get(video_id, fields="status")

    status = payload.get("status")
    if isinstance(status, dict):
        return str(status.get("video_status", "")).lower()
    return str(status or "").lower()


def video_thumbnail(
    *, video_id: str, token: str, client: GraphClient | None = None
) -> str:
    """A frame Meta picked out, as a URL a creative can carry."""
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
    """Remove one image from the ad account's library, by its hash."""
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
    """A delete Meta did not say yes to is not a delete."""
    if payload.get("success") in (True, "true"):
        return
    raise MetaAPIError(
        f"Meta did not confirm the {what} was deleted: {redacted(payload)}"
    )


def _hash_of(payload: dict[str, Any]) -> str:
    """The hash, out of a response keyed by whatever the field was called."""
    images = payload.get("images")
    if not isinstance(images, dict):
        return ""

    for entry in images.values():
        if isinstance(entry, dict) and entry.get("hash"):
            return str(entry["hash"])

    return ""
