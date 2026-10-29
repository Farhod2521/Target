"""What drawing one support message needs, for one reader.

The client sees their own words as "Siz" and the office's as
"Qo'llab-quvvatlash"; the office sees the reverse, with the colleague's
name. Which side a row stands on, its files with this reader's door to
them, the quote above it, whether its sender may still change it and
whether the other side has read it - each one a rule, kept here.
"""

from datetime import datetime
from typing import Any

from app.modules.supportchat.constants import (
    CLIENT,
    STICKERS,
    MessageKind,
    Viewer,
    sticker_emoji,
)
from app.modules.supportchat.models import (
    SupportAttachment,
    SupportConversation,
    SupportMessage,
)
from app.modules.supportchat.preview import clock, preview_text
from app.modules.supportchat.rules import may_change, side_of
from app.modules.supportchat.selectors.messages import Drawn

CLIENT_FILE_URL = "/api/v1/support/files/{id}"
CLIENT_MESSAGE_FILE_URL = "/api/v1/support/messages/{id}/file"
OFFICE_FILE_URL = "/api/v1/office/support/files/{id}"
OFFICE_MESSAGE_FILE_URL = "/api/v1/office/support/messages/{id}/file"
DOORS = {
    CLIENT_FILE_URL: OFFICE_FILE_URL,
    CLIENT_MESSAGE_FILE_URL: OFFICE_MESSAGE_FILE_URL,
}


def message_views(
    drawn: Drawn, *, conversation: SupportConversation, viewer: Viewer, now: datetime
) -> list[dict[str, Any]]:
    return [
        message_view(
            message,
            drawn=drawn,
            conversation=conversation,
            viewer=viewer,
            now=now,
        )
        for message in drawn.messages
    ]


def message_view(
    message: SupportMessage,
    *,
    drawn: Drawn,
    conversation: SupportConversation,
    viewer: Viewer,
    now: datetime,
) -> dict[str, Any]:
    """Everything one row draws, for this reader."""
    side = side_of(message)
    own = side == viewer
    open_ = own and may_change(message=message, now=now)
    rows = drawn.files.get(message.id, [])
    gone = message.deleted_at is not None
    name = sticker_name(message.sticker)
    return {
        "id": str(message.id),
        "side": side,
        "own": own,
        "who": _who(message, viewer),
        "kind": message.kind,
        "body": "" if gone else message.body,
        "sticker": "" if gone or not name else message.sticker,
        "sticker_name": "" if gone else name,
        "sticker_emoji": "" if gone else sticker_emoji(message.sticker),
        "files": [] if gone else _files(message, rows, viewer),
        "quote": None if gone else _quote(message, drawn, viewer),
        "created_at": message.created_at,
        "at": int(message.created_at.timestamp() * 1000),
        "edited_at": message.edited_at if not gone else None,
        "deleted_at": message.deleted_at,
        "editable": open_
        and message.kind not in (MessageKind.STICKER, MessageKind.VOICE),
        "deletable": open_,
        "repliable": not gone,
        "read": own and _read_by_other(message, conversation, side),
        "preview": preview_text(message, rows)[:160],
    }


def sticker_name(code: str) -> str:
    for known, _emoji, name in STICKERS:
        if known == code:
            return str(name)
    return ""


def _read_by_other(
    message: SupportMessage, conversation: SupportConversation, side: str
) -> bool:
    seen = (
        conversation.office_read_at if side == CLIENT else conversation.client_read_at
    )
    return seen is not None and seen >= message.created_at


def _files(
    message: SupportMessage, rows: list[SupportAttachment], viewer: Viewer
) -> list[dict[str, Any]]:
    drawn = [
        _file(
            id=str(row.id),
            kind=row.kind,
            name=row.original_name,
            size=row.size_bytes,
            seconds=row.duration_seconds,
            url=_door(viewer, CLIENT_FILE_URL, row.id),
        )
        for row in rows
    ]
    if message.attachment:
        drawn.append(
            _file(
                id=str(message.id),
                kind=message.kind,
                name=message.original_name,
                size=message.size_bytes,
                seconds=0,
                url=_door(viewer, CLIENT_MESSAGE_FILE_URL, message.id),
            )
        )
    return drawn


def _file(
    *, id: str, kind: str, name: str, size: int, seconds: int, url: str
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": kind,
        "name": name,
        "size": size,
        "seconds": seconds,
        "length": clock(seconds),
        "url": url,
        "view_url": f"{url}?view=1" if url else "",
    }


def _door(viewer: Viewer, pattern: str, pk: object) -> str:
    """This reader's download address: the client's own, or the office's,
    which journals the reading."""
    return (pattern if viewer == CLIENT else DOORS[pattern]).format(id=pk)


def _quote(
    message: SupportMessage, drawn: Drawn, viewer: Viewer
) -> dict[str, Any] | None:
    target = drawn.quotes.get(message.reply_to_id) if message.reply_to_id else None
    if target is None:
        return None
    return {
        "id": str(target.id),
        "who": _who(target, viewer),
        "text": preview_text(target, drawn.files.get(target.id, []))[:120],
        "gone": target.deleted_at is not None,
    }


def _who(message: SupportMessage, viewer: Viewer) -> str:
    """The client reads "Siz" and the team; the office reads names."""
    if viewer == CLIENT:
        return "Siz" if side_of(message) == CLIENT else "Qo'llab-quvvatlash"
    sender = message.sender
    if sender is None:
        return "Qo'llab-quvvatlash"
    return sender.full_name or sender.email
