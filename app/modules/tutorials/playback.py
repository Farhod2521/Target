"""How a lesson's files reach a viewer without being handed over whole.

A ``<video>`` or ``<img>`` tag sends no Authorization header, so each link
carries a short-lived token of its own: who it was issued to, which lesson,
and whether it was the office (which also plays a lesson not yet shown).

The video goes out one piece per request, never more than
``STREAM_PIECE_BYTES``: the player asks for the next range as it plays, and
a plain GET of the link gets the first piece and no more. This keeps the
browser's "save video" and a pasted link from being the file; it does not
stop a screen recorder, and nothing served to a browser can.
"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt
from fastapi import Response, status
from sqlalchemy.orm import Session

from app.api.deps import may_sign_in
from app.common import storage
from app.common.config import settings
from app.common.tokens import ALGORITHM
from app.modules.accounts.models import User
from app.modules.tutorials.constants import (
    PLAY_TOKEN_HOURS,
    STREAM_PIECE_BYTES,
    VIDEO_TYPES,
)
from app.modules.tutorials.exceptions import TutorialNotFound
from app.modules.tutorials.models import Tutorial
from app.modules.tutorials.selectors import youtube_id

TOKEN_KIND = "tutorial"
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_IMAGE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_PRIVATE = {
    "Cache-Control": "private, no-store",
    "Content-Disposition": "inline",
    "X-Content-Type-Options": "nosniff",
}


def issue(*, user: User, tutorial: Tutorial, office: bool, now: datetime) -> str:
    payload = {
        "typ": TOKEN_KIND,
        "sub": str(user.id),
        "tid": str(tutorial.id),
        "office": office,
        "exp": now + timedelta(hours=PLAY_TOKEN_HOURS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def playable(db: Session, *, token: str, tutorial_id: uuid.UUID) -> Tutorial:
    """The lesson this token opens, or 404 - a wrong token says no more than
    a missing lesson does."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise TutorialNotFound from None
    if payload.get("typ") != TOKEN_KIND or payload.get("tid") != str(tutorial_id):
        raise TutorialNotFound
    try:
        user = db.get(User, uuid.UUID(str(payload.get("sub") or "")))
    except ValueError:
        raise TutorialNotFound from None
    row = db.get(Tutorial, tutorial_id)
    if row is None or not may_sign_in(db, user):
        raise TutorialNotFound
    if not row.is_active and not (payload.get("office") and user and user.is_staff):
        raise TutorialNotFound
    return row


def links(
    row: Tutorial, *, user: User, office: bool, now: datetime, base: str
) -> dict[str, Any]:
    """The cover and the video as the frontend draws them.

    ``video.kind`` is ``youtube`` (show ``embed_url`` in an iframe), ``link``
    (another site: open or embed ``url``) or ``file`` (``stream_url`` in a
    ``<video>`` tag, which asks for the pieces by itself).
    """
    token = (
        issue(user=user, tutorial=row, office=office, now=now)
        if row.image or row.video_file
        else ""
    )
    image_url = f"{base}/{row.id}/image?t={token}" if row.image else None
    if row.video_file:
        video: dict[str, Any] = {
            "kind": "file",
            "stream_url": f"{base}/{row.id}/video?t={token}",
        }
    else:
        found = youtube_id(row.video_url)
        video = {
            "kind": "youtube" if found else "link",
            "url": row.video_url,
            "embed_url": (
                f"https://www.youtube-nocookie.com/embed/{found}" if found else None
            ),
        }
    return {"image_url": image_url, "video": video}


def image_response(row: Tutorial) -> Response:
    path = storage.media_path(row.image) if row.image else None
    if path is None or not path.is_file():
        raise TutorialNotFound("Rasm topilmadi.")
    kind = _IMAGE_TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return Response(path.read_bytes(), media_type=kind, headers=_PRIVATE)


def _span(header: str, size: int) -> tuple[int, int] | None:
    """The first range asked for, cut to one piece; ``None`` when it lies
    outside the file."""
    first = header.split(",")[0].strip() if header else "bytes=0-"
    found = _RANGE.match(first)
    if found is None:
        return None
    start_text, end_text = found.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        start = max(size - int(end_text), 0)
        end = size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1, start + STREAM_PIECE_BYTES - 1)


def video_response(row: Tutorial, *, range_header: str) -> Response:
    path = storage.media_path(row.video_file) if row.video_file else None
    if path is None or not path.is_file():
        raise TutorialNotFound("Video topilmadi.")
    size = path.stat().st_size
    span = _span(range_header, size)
    if span is None:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{size}"},
        )
    start, end = span
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read(end - start + 1)
    kind = VIDEO_TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return Response(
        data,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=kind,
        headers={
            **_PRIVATE,
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
        },
    )
