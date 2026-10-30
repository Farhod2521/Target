"""The owner's own file, on its way to Meta, in the domain's types.

Two sources, one destination. A file from the owner's disk is *uploaded*;
one that already lives on their Instagram is *imported*, which is the same
upload with a fetch in front of it. The pair is kept apart in the names
because only one of them can fail for a reason nobody here controls - a
signed URL that expired between being read and being used.

Apart from :class:`metaads.launcher.MetaLauncher` because of one real
difference: **nothing here is rolled back.** An image is identified by the
hash of its contents, so uploading it twice produces the same hash and
creates nothing new - and deleting it could break an ad belonging to a
campaign this product never touched. Everything the launcher creates is the
opposite: made once, owned by one launch, and deleted if the sequence fails.

That is also why nothing here returns an ``ExternalRef``. A ref exists so
that a rollback can name what it has to remove, and these never appear in
``created_refs`` at all.

**The one delete here is the owner's own.** A button on their library, with
a confirmation behind it - never a rollback, never a sweep. It is also why
:meth:`MetaAssets.image_creatives` sits beside it: the caller asks whether
any creative still shows the picture, Meta's own answer and not a mirror's,
and refuses before anything is sent.
"""

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

# What a video Meta refused looks like from here. The file is the owner's
# own and so is the fix - a different file - which makes this an invalid
# request rather than a temporary failure worth retrying.
_VIDEO_REFUSED: Final = "Meta could not process this video"

# How much of somebody's photograph a worker will hold at once.
#
# Generous against what Instagram actually serves - between 190 and 350
# kilobytes a post - and far below what the ad account would accept. It is
# not a Meta limit. It is the line past
# which a picture stops being worth a worker's memory, and it exists
# because ``media_url`` points at a file nobody here chose the size of.
MAX_IMAGE_BYTES: Final = 8 * 1024 * 1024

# The only field a fresh read is for. Asking for the whole row would put
# two more uncertain names between a launch and the one string it needs.
_SOURCE_FIELD: Final = "media_url"

# What a carousel is asked for when it has to be rebuilt as a new advert:
# its own type, and every slide with a file that can still be fetched.
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
    the owner asks - taking one off the library again.

    Stateless like every adapter here: one token per call, one connection
    opened and closed per call.
    """

    def upload_image(
        self,
        *,
        account: ExternalRef,
        data: bytes,
        token: str,
        filename: str = "",
        dry_run: bool = True,
    ) -> str:
        """Returns a **hash**, not an id.

        Meta's own odd one out, and the single detail in this package most
        likely to be got wrong by code written from memory - the failure
        being a creative that builds cleanly and shows nothing.

        ``filename`` is what the library will call it; without one Meta
        names the row "bytes".
        """
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
        """Returns an id for something Meta cannot use yet.

        The caller waits for :meth:`video_ready` before building a creative
        against it. There is no synchronous form of this call, and a fixed
        sleep instead would be a guess about somebody else's queue.

        **How the file travels is decided here, by its size.** Small enough
        and it is one request; past :data:`metaads.chunks.
        CHUNKED_ABOVE_BYTES` it is a session and a series of pieces, which
        is the only form Meta accepts for a large file and the only one a
        failed attempt can carry on from.

        ``resume`` and ``remember`` belong to that second form and are
        ignored by the first, where there is nothing to carry on from.
        Passing ``resume`` forces the session route whatever the size says:
        the caller is finishing an upload that has already begun, and
        starting again would create a second video.
        """
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
        """Give up on a half-sent video, for a caller that has stopped trying.

        Only ever about a session :meth:`upload_video` opened and did not
        finish. What it removes is an object Meta issued an id for and
        nothing refers to; an unfinished video left behind is not an error,
        it is clutter in somebody's library.
        """
        with session(token) as graph:
            cancel_chunked_video(
                account_id=account.id,
                session_id=session_id,
                token=token,
                client=graph,
            )

    def instagram_source(self, *, media_id: str, token: str) -> str:
        """Where the file is **right now**, asked again on purpose.

        ``media_url`` is signed and it expires, so the address a sync wrote
        down is one that fetches nothing an hour later. Nothing stores it;
        this is read immediately before the import that uses it, and the
        gap between the two is the only window that matters.

        Needs the **page** token, like every other Instagram read: it is
        the account's own content, reached through the page it speaks for.

        Empty means Meta withheld the file - licensed audio, or a copyright
        flag - which is an answer and not a failure. The caller refuses the
        launch over it; there is nothing to fall back on.
        """
        with session(token) as graph:
            row = read_instagram_media(
                media_id=media_id, token=token, fields=_SOURCE_FIELD, client=graph
            )
        return str(row.get(_SOURCE_FIELD, ""))

    def instagram_slides(self, *, media_id: str, token: str) -> list[InstagramSlide]:
        """Every slide of a carousel post, in its order - or nothing.

        Empty for a post that is not a carousel, which is how the caller
        tells the two apart: the mirror stores one row per post and cannot
        say, and the parent's own ``media_url`` is one frame Meta picked.

        Read again rather than stored, for ``instagram_source``'s reason -
        every address here is signed and expires. A slide whose file Meta
        withholds comes back with an empty address and is kept, so the
        caller refuses the post rather than quietly dropping one picture.
        """
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
        """A picture that already lives on Instagram, into this ad account.

        Two calls that have to be one method, because between them the file
        exists only in memory: fetched from the CDN Meta serves the post on,
        then handed to ``/act_<id>/adimages`` as base64. That edge accepts
        no URL, which is the entire reason for the round trip - the video
        edge does, and :meth:`import_video` is shorter by exactly that much.

        ``media_url`` must be **freshly read**. It is signed and it expires,
        so an address stored an hour ago fetches nothing; the caller reads
        the post again immediately before calling this.

        A rehearsal fetches nothing. Downloading a file only to hand it to
        an upload that will not happen would be the one call a dry run made
        for real, against somebody else's bandwidth.

        No conversion happens and none is needed: the CDN answers
        ``image/jpeg`` whatever the URL's extension says - see
        :mod:`metaads.cdn`.

        The fetch sits **inside** the session, and not for the connection.
        ``session`` is what turns a Meta failure into the domain's own, and
        a download raising outside it would put ``MediaTooLargeError`` -
        this package's word, not the domain's - in front of a service. It
        costs nothing to open first: the client connects lazily.
        """
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
        """A reel into this ad account, without it passing through here.

        Meta fetches the file itself, so a worker holds none of it and the
        length of somebody's video stops being our problem. There is no
        ceiling for the same reason there is no download.

        Returns an id for something not usable yet, like every video here -
        the caller waits on :meth:`video_ready` before building against it.
        """
        with session(token) as graph:
            return upload_video_from_url(
                account_id=account.id,
                file_url=media_url,
                token=token,
                client=graph,
                dry_run=dry_run,
            )

    def video_ready(self, *, video_id: str, token: str) -> bool:
        """Whether transcoding finished. Raises if it failed.

        Three answers collapsed into two: ready is true, refused raises,
        and everything else - including a status Meta did not send - is
        false, meaning ask again. Treating an unknown status as ready builds
        a creative that Meta rejects several calls later, by which point
        there is a campaign and an ad set to undo.
        """
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
        """The hashes among these that this ad account itself holds.

        Asked before a creative names a library picture: Meta accepts a
        creative built on another account's hash and fails the ad only once
        it starts delivering.
        """
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

    def delete_video(
        self,
        *,
        account: ExternalRef,
        video_id: str,
        token: str,
        dry_run: bool = True,
    ) -> None:
        """Take one video off the library. See the module docstring."""
        with session(token) as graph:
            delete_video(
                account_id=account.id,
                video_id=video_id,
                token=token,
                client=graph,
                dry_run=dry_run,
            )
