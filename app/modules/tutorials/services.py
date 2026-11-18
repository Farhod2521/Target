"""Writing tutorials in the office: the fields, the cover, the video in pieces.

The video comes up the way the wizard's does - ``append_chunk`` once per
piece, then the create or the edit names the upload - so a long lesson
survives a dropped connection. Every file lives under MEDIA_ROOT outside
the one folder nginx serves; the cabinet reaches them through
``app.modules.tutorials.playback``.
"""

import fcntl
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.common.images import read_size
from app.modules.accounts.models import User
from app.modules.ads.exceptions import ChunkOutOfPlace, ChunkRefused, UploadIncomplete
from app.modules.tutorials.constants import (
    DESCRIPTION_MAX,
    IMAGE_DIR,
    IMAGE_TYPES,
    MAX_IMAGE_MB,
    MAX_VIDEO_MB,
    PARTIAL_UPLOAD_DIR,
    PARTIAL_UPLOAD_HOURS,
    TITLE_MAX,
    UPLOAD_CHUNK_BYTES,
    VIDEO_DIR,
    VIDEO_TYPES,
    VIDEO_URL_MAX,
    TutorialLanguage,
    TutorialPlace,
    TutorialType,
)
from app.modules.tutorials.models import Tutorial
from app.modules.tutorials.models.tutorial import column

logger = logging.getLogger(__name__)
_SUFFIX = ".part"
_MB = 1024 * 1024
# Half-sent videos one member may have going at once.
_OPEN_UPLOADS = 3
_HEADER_BYTES = 64 * 1024


# -- the pieces ------------------------------------------------------------------------


def _partial(*, staff_id: uuid.UUID, upload_id: str, total: int) -> Path:
    try:
        ident = uuid.UUID(upload_id)
    except (TypeError, ValueError) as exc:
        raise ChunkRefused from exc
    return storage.media_path(
        f"{PARTIAL_UPLOAD_DIR}/{staff_id}/{ident}.{total}{_SUFFIX}"
    )


def append_chunk(
    *, staff_id: uuid.UUID, upload_id: str, total: int, offset: int, data: bytes
) -> int:
    """Add one piece to the end of the video. Returns how much is here now."""
    if total <= 0 or total > MAX_VIDEO_MB * _MB or len(data) > UPLOAD_CHUNK_BYTES:
        raise ChunkRefused
    if offset < 0 or offset + len(data) > total:
        raise ChunkRefused
    path = _partial(staff_id=staff_id, upload_id=upload_id, total=total)
    if (
        not path.exists()
        and path.parent.is_dir()
        and sum(1 for _ in path.parent.glob(f"*{_SUFFIX}")) >= _OPEN_UPLOADS
    ):
        raise ChunkRefused
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        here = handle.seek(0, os.SEEK_END)
        if here != offset:
            raise ChunkOutOfPlace(offset=here)
        handle.write(data)
        return here + len(data)


@dataclass(frozen=True, slots=True)
class VideoUpload:
    """A video whose every piece is here, not yet a lesson's."""

    path: Path
    name: str


def assembled_video(
    *, staff_id: uuid.UUID, upload_id: str, total: int, name: str
) -> VideoUpload:
    path = _partial(staff_id=staff_id, upload_id=upload_id, total=total)
    if not path.is_file() or path.stat().st_size != total:
        raise UploadIncomplete
    clean = PurePosixPath(name.replace("\\", "/")).name.strip()[:200]
    if not clean:
        raise ChunkRefused
    return VideoUpload(path=path, name=clean)


def drop_stale_partials(*, now: datetime) -> int:
    """Delete every half-sent video nobody has added to in a day."""
    root = storage.media_path(PARTIAL_UPLOAD_DIR)
    if not root.is_dir():
        return 0
    cutoff = (now - timedelta(hours=PARTIAL_UPLOAD_HOURS)).timestamp()
    dropped = 0
    for path in root.glob(f"*/*{_SUFFIX}"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                dropped += 1
        except FileNotFoundError:
            continue
    for folder in root.iterdir():
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if dropped:
        logger.info("half-sent tutorial videos dropped", extra={"count": dropped})
    return dropped


# -- the checks ------------------------------------------------------------------------


def _suffix(name: str) -> str:
    return PurePosixPath(name).suffix.lower().lstrip(".")


def _video_problem(video: VideoUpload) -> str:
    kind = _suffix(video.name)
    if kind not in VIDEO_TYPES:
        return "Faqat " + ", ".join(VIDEO_TYPES).upper() + " video yuklang."
    with video.path.open("rb") as handle:
        head = handle.read(16)
    if kind == "mp4" and head[4:8] != b"ftyp":
        return "Bu fayl MP4 video emas."
    if kind == "webm" and not head.startswith(b"\x1a\x45\xdf\xa3"):
        return "Bu fayl WEBM video emas."
    return ""


def _image_problem(image: Any) -> str:
    if _suffix(image.filename or "") not in IMAGE_TYPES:
        return "Faqat " + ", ".join(IMAGE_TYPES).upper() + " rasm yuklang."
    if (image.size or 0) > MAX_IMAGE_MB * _MB:
        return f"Rasm {MAX_IMAGE_MB} MB dan oshmasin."
    head = image.file.read(_HEADER_BYTES)
    image.file.seek(0)
    if read_size(head) is None:
        return "Rasmni o'qib bo'lmadi. Boshqa rasm tanlang."
    return ""


def _url_problem(url: str) -> str:
    if len(url) > VIDEO_URL_MAX:
        return f"Havola {VIDEO_URL_MAX} belgidan oshmasin."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "To'liq havola yozing: https:// bilan boshlansin."
    return ""


# -- the writes ------------------------------------------------------------------------


@dataclass(slots=True)
class VersionIn:
    """One language of a lesson, as the form sent it."""

    title: str = ""
    description: str = ""
    video_url: str = ""
    image: Any = None
    video: VideoUpload | None = None
    remove_image: bool = False
    remove_video: bool = False


@dataclass(slots=True)
class TutorialIn:
    type: str
    is_active: bool
    # By language; a language left out is as if sent empty.
    versions: dict[str, VersionIn] = field(default_factory=dict)
    # None keeps the row's places (an edit from a form that has no such field).
    places: list[str] | None = None


@dataclass(slots=True)
class Saved:
    """The row, and the files to delete once the commit has or has not held."""

    row: Tutorial
    stale: list[str] = field(default_factory=list)
    fresh: list[str] = field(default_factory=list)


def _kept(row: Tutorial | None, part: str, language: str, *, removed: bool) -> bool:
    return bool(row is not None and row.part(part, language) and not removed)


def _given(body: VersionIn, *, row: Tutorial | None, language: str) -> bool:
    """Whether this language is written at all: anything typed or sent, or
    a file of it kept from before."""
    return bool(
        body.title.strip()
        or body.description.strip()
        or body.video_url.strip()
        or body.image is not None
        or body.video is not None
        or _kept(row, "image", language, removed=body.remove_image)
        or _kept(row, "video_file", language, removed=body.remove_video)
    )


def _version_problems(
    body: VersionIn, *, row: Tutorial | None, language: str
) -> dict[str, str]:
    """A written language's problems, under its own field names."""
    problems: dict[str, str] = {}
    title = body.title.strip()
    if not title:
        problems["title"] = "Sarlavhani yozing."
    elif len(title) > TITLE_MAX:
        problems["title"] = f"Sarlavha {TITLE_MAX} belgidan oshmasin."
    if len(body.description) > DESCRIPTION_MAX:
        problems["description"] = f"Izoh {DESCRIPTION_MAX} belgidan oshmasin."
    if body.image is not None and (problem := _image_problem(body.image)):
        problems["image"] = problem
    url = body.video_url.strip()
    if url and (problem := _url_problem(url)):
        problems["video_url"] = problem
    if body.video is not None and (problem := _video_problem(body.video)):
        problems["video"] = problem
    has_file = body.video is not None or _kept(
        row, "video_file", language, removed=body.remove_video
    )
    if url and has_file:
        problems.setdefault(
            "video_url", "Yo havola, yo yuklangan video - ikkalasi birga emas."
        )
    elif not url and not has_file:
        problems.setdefault("video", "Video havolasini yozing yoki videoni yuklang.")
    return {column(name, language): text for name, text in problems.items()}


def _problems(body: TutorialIn, *, row: Tutorial | None) -> dict[str, str]:
    problems: dict[str, str] = {}
    if body.type not in TutorialType.values:
        problems["type"] = "Turini tanlang."
    if any(place not in TutorialPlace.values for place in body.places or ()):
        problems["places"] = "Bunday oyna yo'q."
    written = [
        language
        for language in TutorialLanguage.values
        if _given(body.versions.get(language, VersionIn()), row=row, language=language)
    ]
    # Nothing in any language: ask for the Uzbek one, as before languages.
    for language in written or [TutorialLanguage.UZ.value]:
        problems |= _version_problems(
            body.versions.get(language, VersionIn()), row=row, language=language
        )
    return problems


def _write_version(
    row: Tutorial,
    body: VersionIn,
    *,
    language: str,
    written: bool,
    saved: Saved,
    now: datetime,
) -> None:
    """One language's columns as the form says; a language not written is
    emptied, its files with it."""
    if not written:
        body = VersionIn(remove_image=True, remove_video=True)
    row.set_part("title", language, body.title.strip())
    row.set_part("description", language, body.description.strip())
    row.set_part("video_url", language, body.video_url.strip())
    if body.image is not None or body.remove_image:
        saved.stale.append(row.part("image", language))
        row.set_part("image", language, "")
    if body.image is not None:
        name = storage.save(
            body.image.file,
            folder=storage.dated(IMAGE_DIR, now=now),
            filename=body.image.filename or "cover.jpg",
        )
        row.set_part("image", language, name)
        saved.fresh.append(name)
    if body.video is not None or body.remove_video or row.part("video_url", language):
        saved.stale.append(row.part("video_file", language))
        row.set_part("video_file", language, "")
    if body.video is not None:
        name = storage.move(
            body.video.path,
            folder=storage.dated(VIDEO_DIR, now=now),
            filename=body.video.name,
        )
        row.set_part("video_file", language, name)
        saved.fresh.append(name)


def save_tutorial(
    db: Session, *, body: TutorialIn, row: Tutorial | None, actor: User
) -> Saved:
    """Create, or rewrite ``row``. Refuses field by field before any file moves."""
    problems = _problems(body, row=row)
    if problems:
        raise InputRefused(problems)
    written = {
        language: _given(
            body.versions.get(language, VersionIn()), row=row, language=language
        )
        for language in TutorialLanguage.values
    }
    if row is None:
        row = Tutorial(created_by_id=actor.id)
        db.add(row)
    saved = Saved(row=row)
    row.type = body.type
    if body.places is not None:
        # In the catalogue's order, each once, whatever order the form sent.
        row.places = [place for place in TutorialPlace.values if place in body.places]
    elif row.places is None:
        row.places = []
    row.is_active = body.is_active
    now = utcnow()
    for language in TutorialLanguage.values:
        _write_version(
            row,
            body.versions.get(language, VersionIn()),
            language=language,
            written=written[language],
            saved=saved,
            now=now,
        )
    db.flush()
    saved.stale = [name for name in saved.stale if name]
    logger.info("tutorial %s saved by %s", row.id, actor.id)
    return saved


def delete_tutorial(db: Session, *, row: Tutorial) -> list[str]:
    """Delete the row. Returns its files, to delete after the commit."""
    files = row.files()
    db.delete(row)
    db.flush()
    return files
