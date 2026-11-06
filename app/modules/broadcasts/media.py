"""A broadcast's picture, reached by a link that carries its own token.

An ``<img>`` sends no Authorization header. The office's link also opens a
draft's picture; the site's opens only what the site shows.
"""

import uuid
from datetime import datetime, timedelta

import jwt
from fastapi import Response
from sqlalchemy.orm import Session

from app.common import storage
from app.common.config import settings
from app.common.tokens import ALGORITHM
from app.modules.broadcasts.constants import IMAGE_TOKEN_HOURS
from app.modules.broadcasts.exceptions import BroadcastNotFound
from app.modules.broadcasts.models import Broadcast
from app.modules.broadcasts.selectors import broadcast_by_id, site_broadcast

BASE = "/api/v1/news"
TOKEN_KIND = "broadcast_image"
_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_PRIVATE = {
    "Cache-Control": "private, max-age=3600",
    "Content-Disposition": "inline",
    "X-Content-Type-Options": "nosniff",
}


def image_url(row: Broadcast, *, office: bool, now: datetime) -> str:
    if not row.image:
        return ""
    token = jwt.encode(
        {
            "typ": TOKEN_KIND,
            "bid": str(row.id),
            "office": office,
            "exp": now + timedelta(hours=IMAGE_TOKEN_HOURS),
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    return f"{BASE}/{row.id}/image?t={token}"


def image_response(db: Session, *, broadcast_id: uuid.UUID, token: str) -> Response:
    """The picture, or 404 - a wrong token says no more than a missing one."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise BroadcastNotFound from None
    if payload.get("typ") != TOKEN_KIND or payload.get("bid") != str(broadcast_id):
        raise BroadcastNotFound
    row = (
        broadcast_by_id(db, broadcast_id)
        if payload.get("office")
        else site_broadcast(db, broadcast_id)
    )
    path = storage.media_path(row.image) if row is not None and row.image else None
    if path is None or not path.is_file():
        raise BroadcastNotFound("Rasm topilmadi.")
    kind = _TYPES.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return Response(path.read_bytes(), media_type=kind, headers=_PRIVATE)
