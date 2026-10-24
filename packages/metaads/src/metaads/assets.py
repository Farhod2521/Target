"""The owner's own file, on its way to Meta, in the domain's types."""

from collections.abc import Callable
from typing import Final

from adskit.errors import InvalidRequest
from adskit.refs import ExternalRef

from metaads.adapter import session
from metaads.cdn import download_media
from metaads.chunks import (
    CHUNKED_ABOVE_BYTES,
    VideoSession,
    cancel_chunked_video,
    upload_video_in_chunks,
)
from metaads.creatives import describe_image, image_creatives, own_image_hashes
from metaads.discovery import read_instagram_media
from metaads.dto import MediaDTO
from metaads.dto_base import MetaDTO
from metaads.uploads import (
    VIDEO_ERROR,
    VIDEO_READY,
    Readable,
    delete_image,
    delete_video,
    upload_image,
    upload_video,
    upload_video_from_url,
    video_status,
    video_thumbnail,
)

_VIDEO_REFUSED: Final = "Meta could not process this video"

MAX_IMAGE_BYTES: Final = 8 * 1024 * 1024

_SOURCE_FIELD: Final = "media_url"

_SLIDE_FIELDS: Final = "media_type,children{id,media_type,media_url}"
_CAROUSEL: Final = "CAROUSEL_ALBUM"
_VIDEO_SLIDE: Final = "VIDEO"


class InstagramSlide(MetaDTO):
    """One picture or video inside an Instagram carousel, freshly read."""

    media_id: str
    media_url: str
    is_video: bool


class MetaAssets:
    """Uploading a picture or a video, waiting for the video, and - when
    the owner asks - taking one off the library again."""

    def upload_image(
        self,
        *,
        account: ExternalRef,
        data: bytes,
        token: str,
        filename: str = "",
        dry_run: bool = True,
    ) -> str:
        """Returns a **hash**, not an id."""
        with session(token) as graph:
            return upload_image(
                account_id=account.id,
                data=data,
                token=token,
                filename=filename,
                client=graph,
                dry_run=dry_run,
            )

    def upload_video(
        self,
        *,
        account: ExternalRef,
        file: Readable,
        file_size: int,
        filename: str,
        token: str,
        resume: VideoSession | None = None,
        remember: Callable[[VideoSession], None] | None = None,
        dry_run: bool = True,
    ) -> str:
        """Returns an id for something Meta cannot use yet."""
        if file_size > CHUNKED_ABOVE_BYTES or resume is not None:
            with session(token) as graph:
                return upload_video_in_chunks(
                    account_id=account.id,
                    file=file,
                    file_size=file_size,
                    filename=filename,
                    token=token,
                    client=graph,
                    resume=resume,
                    remember=remember,
                    dry_run=dry_run,
                )

        with session(token) as graph:
            return upload_video(
                account_id=account.id,
                file=file,
                filename=filename,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

    def abandon_video(
        self, *, account: ExternalRef, session_id: str, token: str
    ) -> None:
        """Give up on a half-sent video, for a caller that has stopped trying."""
        with session(token) as graph:
            cancel_chunked_video(
                account_id=account.id,
                session_id=session_id,
                token=token,
                client=graph,
            )

    def instagram_source(self, *, media_id: str, token: str) -> str:
        """Where the file is **right now**, asked again on purpose."""
        with session(token) as graph:
            row = read_instagram_media(
                media_id=media_id, token=token, fields=_SOURCE_FIELD, client=graph
            )
        return str(row.get(_SOURCE_FIELD, ""))

    def instagram_slides(self, *, media_id: str, token: str) -> list[InstagramSlide]:
        """Every slide of a carousel post, in its order - or nothing."""
        with session(token) as graph:
            row = read_instagram_media(
                media_id=media_id, token=token, fields=_SLIDE_FIELDS, client=graph
            )
        if str(row.get("media_type", "")) != _CAROUSEL:
            return []
        children = row.get("children") or {}
        items = children.get("data", []) if isinstance(children, dict) else []
        return [
            InstagramSlide(
                media_id=str(item.get("id", "")),
                media_url=str(item.get("media_url", "")),
                is_video=str(item.get("media_type", "")) == _VIDEO_SLIDE,
            )
            for item in items
            if isinstance(item, dict)
        ]

    def import_image(
        self,
        *,
        account: ExternalRef,
        media_url: str,
        token: str,
        dry_run: bool = True,
    ) -> str:
        """A picture that already lives on Instagram, into this ad account."""
        if dry_run:
            return upload_image(
                account_id=account.id, data=b"", token=token, dry_run=True
            )

        with session(token) as graph:
            data = download_media(url=media_url, max_bytes=MAX_IMAGE_BYTES)
            return upload_image(
                account_id=account.id,
                data=data,
                token=token,
                client=graph,
                dry_run=False,
            )

    def import_video(
        self,
        *,
        account: ExternalRef,
        media_url: str,
        token: str,
        dry_run: bool = True,
    ) -> str:
        """A reel into this ad account, without it passing through here."""
        with session(token) as graph:
            return upload_video_from_url(
                account_id=account.id,
                file_url=media_url,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

    def video_ready(self, *, video_id: str, token: str) -> bool:
        """Whether transcoding finished. Raises if it failed."""
        with session(token) as graph:
            status = video_status(video_id=video_id, token=token, client=graph)

        if status == VIDEO_ERROR:
            raise InvalidRequest(_VIDEO_REFUSED, code=VIDEO_ERROR)
        return status == VIDEO_READY

    def video_thumbnail(self, *, video_id: str, token: str) -> str:
        """A frame to put in the creative. Meta refuses one without it."""
        with session(token) as graph:
            return video_thumbnail(video_id=video_id, token=token, client=graph)

    def describe_image(
        self, *, account: ExternalRef, image_hash: str, token: str
    ) -> MediaDTO:
        """What an upload's hash names: the address, the size, the name."""
        with session(token) as graph:
            return describe_image(
                account_id=account.id, image_hash=image_hash, token=token, client=graph
            )

    def own_images(
        self, *, account: ExternalRef, hashes: list[str], token: str
    ) -> frozenset[str]:
        """The hashes among these that this ad account itself holds."""
        with session(token) as graph:
            return own_image_hashes(
                account_id=account.id, hashes=hashes, token=token, client=graph
            )

    def image_creatives(
        self, *, account: ExternalRef, image_hash: str, token: str
    ) -> tuple[str, ...]:
        """Every creative that shows this image. Asked before a delete."""
        with session(token) as graph:
            return image_creatives(
                account_id=account.id, image_hash=image_hash, token=token, client=graph
            )

    def delete_image(
        self,
        *,
        account: ExternalRef,
        image_hash: str,
        token: str,
        dry_run: bool = True,
    ) -> None:
        """Take one image off the library. See the module docstring."""
        with session(token) as graph:
            delete_image(
                account_id=account.id,
                image_hash=image_hash,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

    def delete_video(self, *, video_id: str, token: str, dry_run: bool = True) -> None:
        """Take one video off the library. See the module docstring."""
        with session(token) as graph:
            delete_video(video_id=video_id, token=token, client=graph, dry_run=dry_run)
