"""Pictures from the phone, refused here when Meta would refuse them."""

from pathlib import PurePosixPath
from typing import BinaryIO, Protocol

from pydantic import BaseModel, Field

from app.common.images import MAX_HEADER_BYTES, read_size
from app.modules.ads.constants import (
    ALLOWED_UPLOAD_TYPES,
    ALLOWED_VIDEO_TYPES,
    MAX_BRIEF_CHARS,
    MAX_IMAGE_MB,
    MAX_VIDEO_MB,
    MIN_IMAGE_SIDE,
    TextMode,
)
from app.modules.ads.inputs import Problems

MB = 1024 * 1024
NOTHING_CHOSEN = "Davom etish uchun kamida bitta rasm yoki video tanlang."


class SentFile(Protocol):
    filename: str | None
    file: BinaryIO
    size: int | None


class MediaTextIn(BaseModel):
    """One text for every advert, or one per advert, keyed by variant id."""

    mode: TextMode | None = Field(None, description="Left out: the mode kept.")
    shared: str | None = Field(None, max_length=MAX_BRIEF_CHARS)
    briefs: dict[str, str] = Field(default_factory=dict)
    asset_briefs: dict[str, str] = Field(
        default_factory=dict, description="Texts for library tiles chosen just now."
    )


class MediaContinueIn(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    text: MediaTextIn | None = None


def ceiling_mb(name: str) -> int:
    suffix = PurePosixPath(name).suffix.lstrip(".").lower()
    return MAX_VIDEO_MB if suffix in ALLOWED_VIDEO_TYPES else MAX_IMAGE_MB


def check_file(
    upload: SentFile, *, problems: Problems, field: str, number: int | None
) -> None:
    """The type, the size and - for a picture - the smallest side."""
    name = upload.filename or ""
    label = f"{number}-fayl" if number is not None else "Fayl"
    suffix = PurePosixPath(name).suffix.lstrip(".").lower()
    if suffix not in ALLOWED_UPLOAD_TYPES:
        allowed = ", ".join(ALLOWED_UPLOAD_TYPES)
        problems.add(field, f"{label}: faqat {allowed} fayllari qabul qilinadi.")
        return
    limit = ceiling_mb(name)
    size = upload.size
    if size is None:
        upload.file.seek(0, 2)
        size = upload.file.tell()
        upload.file.seek(0)
    if size > limit * MB:
        problems.add(field, f"{label} juda katta. Eng ko'pi {limit} MB.")
        return
    header = upload.file.read(MAX_HEADER_BYTES)
    upload.file.seek(0)
    found = read_size(header)
    if found is not None and min(found) < MIN_IMAGE_SIDE:
        problems.add(
            field,
            f"{label}: rasm juda kichik. Kamida {MIN_IMAGE_SIDE} x "
            f"{MIN_IMAGE_SIDE} piksel bo'lsin.",
        )


def asset_briefs(text: MediaTextIn, *, variants: dict[str, str]) -> dict[str, str]:
    """Every per-advert text, keyed by the variant it now belongs to.

    ``variants`` maps a library asset id to the variant made from it.
    """
    briefs = dict(text.briefs)
    for asset_id, brief in text.asset_briefs.items():
        variant_id = variants.get(asset_id)
        if variant_id:
            briefs.setdefault(variant_id, brief)
    return briefs


__all__ = [
    "NOTHING_CHOSEN",
    "MediaContinueIn",
    "MediaTextIn",
    "asset_briefs",
    "check_file",
]
