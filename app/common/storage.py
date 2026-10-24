"""Files on disk under MEDIA_ROOT, named the way Django's FileField names them."""

import shutil
import uuid
from datetime import datetime
from pathlib import Path, PurePath
from typing import BinaryIO

from app.common.config import settings


def media_path(name: str) -> Path:
    root = Path(settings.media_root).resolve()
    path = (root / name).resolve()
    if root not in path.parents and path != root:
        raise ValueError("a stored name escapes MEDIA_ROOT")
    return path


def dated(folder: str, *, now: datetime) -> str:
    """``upload_to="x/%Y/%m/"`` - the folder for a file saved now."""
    return now.strftime(folder)


def save(
    stream: BinaryIO, *, folder: str, filename: str, keep_name: bool = False
) -> str:
    """Write ``stream`` under ``folder`` and return the stored name, Django-style."""
    suffix = PurePath(filename).suffix.lower()[:8]
    stem = PurePath(filename).stem[:80] if keep_name else uuid.uuid4().hex
    name = f"{folder.strip('/')}/{stem}{suffix}"
    path = media_path(name)
    while keep_name and path.exists():
        name = f"{folder.strip('/')}/{stem}_{uuid.uuid4().hex[:7]}{suffix}"
        path = media_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        shutil.copyfileobj(stream, out)
    return name


def delete(name: str) -> None:
    if not name:
        return
    try:
        media_path(name).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def url(name: str) -> str:
    return f"{settings.media_url.rstrip('/')}/{name}" if name else ""


def size(name: str) -> int:
    try:
        return media_path(name).stat().st_size
    except (OSError, ValueError):
        return 0
