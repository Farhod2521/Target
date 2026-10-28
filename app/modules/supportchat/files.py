"""Handing an attached file back, to either end of the chat.

A download by default. A picture, a video or a voice may also be shown in
the page when asked with ``?view=1`` - its type is then read off the
stored suffix, never off the ``mime`` the sender's browser claimed: a
"picture" declared as HTML and served inline would run as a page here.

Shown media answers a byte range, at most ``CHUNK_BYTES`` at a time:
Safari will not play audio or video from a server that cannot send part
of a file.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Final

from fastapi import Response
from fastapi.responses import FileResponse

from app.common import storage
from app.common.exceptions import NotFound
from app.modules.supportchat.constants import MessageKind
from app.modules.supportchat.models import SupportAttachment, SupportMessage

INLINE_TYPES: Final[dict[str, dict[str, str]]] = {
    MessageKind.IMAGE: {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    },
    MessageKind.VIDEO: {".mp4": "video/mp4", ".mov": "video/quicktime"},
    MessageKind.VOICE: {
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
    },
}

RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_BYTES: Final = 2 * 1024 * 1024


def attachment_response(
    *, message: SupportMessage, view: bool, range_header: str
) -> Response:
    """A message's own file, from before files had rows of their own."""
    return file_response(
        name=message.attachment,
        filename=message.original_name,
        kind=message.kind,
        mime=message.mime,
        view=view,
        range_header=range_header,
    )


def stored_file_response(
    *, attachment: SupportAttachment, view: bool, range_header: str
) -> Response:
    """One of a message's files."""
    return file_response(
        name=attachment.file,
        filename=attachment.original_name,
        kind=attachment.kind,
        mime=attachment.mime,
        view=view,
        range_header=range_header,
    )


def file_response(
    *, name: str, filename: str, kind: str, mime: str, view: bool, range_header: str
) -> Response:
    """The file, shown when it is media asked to be seen, else saved."""
    try:
        path = storage.media_path(name)
    except ValueError:
        raise NotFound("Fayl topilmadi.") from None
    if not path.is_file():
        raise NotFound("Fayl topilmadi.")
    shown = _inline_type(name=name, kind=kind) if view else ""
    wanted = RANGE.match(range_header or "") if shown else None
    if wanted:
        return _part(path=path, wanted=wanted, content_type=shown)
    response = FileResponse(
        path,
        filename=filename or "fayl",
        media_type=shown or mime or "application/octet-stream",
        content_disposition_type="inline" if shown else "attachment",
    )
    if shown:
        response.headers["Accept-Ranges"] = "bytes"
    return response


def _inline_type(*, name: str, kind: str) -> str:
    """The type to show it as, or empty when it is only ever saved."""
    return INLINE_TYPES.get(kind, {}).get(PurePosixPath(name or "").suffix.lower(), "")


def _part(*, path: Path, wanted: re.Match[str], content_type: str) -> Response:
    """206 with the asked-for bytes, or 416 when they are not in the file."""
    size = path.stat().st_size
    first, last = wanted.group(1), wanted.group(2)
    if first:
        start = int(first)
        end = int(last) if last else min(start + CHUNK_BYTES, size) - 1
    elif last:
        start, end = max(size - int(last), 0), size - 1
    else:
        start, end = 0, size - 1
    end = min(end, size - 1, start + CHUNK_BYTES - 1)
    if start >= size or start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    with path.open("rb") as handle:
        handle.seek(start)
        body = handle.read(end - start + 1)
    return Response(
        body,
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
        },
    )
