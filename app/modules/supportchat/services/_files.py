"""The files a message carries: checked before anything is written, then
stored one row each.

Checked as a whole before the message row exists, so a send with one bad
file among ten writes nothing. What a file is comes from its suffix, never
from the type the browser claimed; a voice recording is a voice because it
came in as one.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Final

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.common import storage
from app.modules.supportchat.constants import (
    ALLOWED_VOICE_SUFFIXES,
    MAX_FILES_PER_MESSAGE,
    MAX_SEND_BYTES,
    MAX_SEND_MB,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    MAX_VOICE_SECONDS,
    MessageKind,
    kind_for_filename,
)
from app.modules.supportchat.drafts import Voice
from app.modules.supportchat.exceptions import (
    SendTooLarge,
    TooManyFiles,
    UnsupportedFileType,
    UploadTooLarge,
    VoiceRefused,
)
from app.modules.supportchat.models import SupportAttachment, SupportMessage

# Django's ``attachment_path``: a random name under a dated directory.
FOLDER: Final = "supportchat/%Y/%m"


@dataclass(frozen=True, slots=True)
class Checked:
    """One file that passed, with what the row records about it."""

    upload: UploadFile
    kind: MessageKind
    name: str
    size: int
    seconds: int = 0


def upload_size(upload: UploadFile) -> int:
    if upload.size is not None:
        return upload.size
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def checked_files(*, files: tuple[UploadFile, ...]) -> list[Checked]:
    """Every file of an album, or the reason none of them may go."""
    if len(files) > MAX_FILES_PER_MESSAGE:
        raise TooManyFiles(MAX_FILES_PER_MESSAGE)
    passed = []
    for upload in files:
        kind = kind_for_filename(upload.filename or "")
        if kind is None:
            raise UnsupportedFileType
        size = upload_size(upload)
        if size > MAX_UPLOAD_BYTES:
            raise UploadTooLarge(MAX_UPLOAD_MB)
        passed.append(Checked(upload=upload, kind=kind, name=_name(upload), size=size))
    if sum(item.size for item in passed) > MAX_SEND_BYTES:
        raise SendTooLarge(MAX_SEND_MB)
    return passed


def checked_voice(*, voice: Voice) -> Checked:
    """A recording that may be a voice message, or why not."""
    upload = voice.upload
    suffix = PurePosixPath(upload.filename or "").suffix.lstrip(".").lower()
    size = upload_size(upload)
    if (
        suffix not in ALLOWED_VOICE_SUFFIXES
        or not 0 < voice.seconds <= MAX_VOICE_SECONDS
        or not 0 < size <= MAX_UPLOAD_BYTES
    ):
        raise VoiceRefused(MAX_VOICE_SECONDS)
    return Checked(
        upload=upload,
        kind=MessageKind.VOICE,
        name=_name(upload),
        size=size,
        seconds=voice.seconds,
    )


def store_files(
    db: Session, *, message: SupportMessage, files: list[Checked], now: datetime
) -> None:
    """One row per file, in the order they were picked, saved under a
    random name."""
    for position, item in enumerate(files):
        item.upload.file.seek(0)
        name = storage.save(
            item.upload.file,
            folder=storage.dated(FOLDER, now=now),
            filename=item.upload.filename or "fayl",
        )
        db.add(
            SupportAttachment(
                owner_id=message.owner_id,
                message_id=message.id,
                position=position,
                kind=item.kind,
                file=name,
                original_name=item.name,
                size_bytes=item.size,
                mime=(item.upload.content_type or "")[:128],
                duration_seconds=item.seconds,
            )
        )


def _name(upload: UploadFile) -> str:
    return (upload.filename or "")[:255]
