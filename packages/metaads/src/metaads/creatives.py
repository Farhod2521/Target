"""What an advertiser already has, ready to be put in an ad.

Four Graph edges - ``adimages``, ``advideos``, a page's ``posts`` and an
Instagram account's ``media`` - and one shape out. They are read together
because the screen that shows them is one grid and the choice between them
is one choice: somebody picking a picture does not care which edge it came
from.

What differs underneath is what the choice then costs. An ad account's
image is already there and its hash goes straight into a creative; an
Instagram post is a file somewhere else that has to be fetched and
uploaded first. That is why the two are separate kinds and not one.

This module parses; :mod:`metaads.discovery` returns the same rows raw for
the staff console. Both exist on purpose - the console is where a shape is
looked at before code is written against it, and this is that code.

An image is identified by its ``hash``. Everything else in Meta's model is
identified by an ``id``, which makes this the single field most likely to
be got wrong by anything written from memory.
"""

from typing import Any, Final

from metaads.client import GraphClient
from metaads.discovery import (
    IMAGE_USAGE_FIELDS,
    list_images,
    list_page_posts,
    list_videos,
    read_images,
)
from metaads.discovery import list_instagram_media as list_instagram_media_rows
from metaads.discovery import (
    list_recent_instagram_media as list_recent_instagram_media_rows,
)
from metaads.dto import MediaDTO

IMAGE: Final = "image"
VIDEO: Final = "video"
POST: Final = "post"

# What an ad account id carries in front of the number an image row names
# its owner by.
_ACCOUNT_PREFIX: Final = "act_"

# Instagram's two, kept apart from the ad account's own. The words look
# alike and the identifiers are nothing alike: ``image`` carries a **hash**
# the ad account already holds, and ``ig_image`` carries a post id whose
# file has not been uploaded anywhere yet. Flattening them would make the
# difference invisible at exactly the moment it decides whether a creative
# is one call or three.
IG_IMAGE: Final = "ig_image"
IG_VIDEO: Final = "ig_video"

# Where a post was published. A feed post and a reel can both become an ad;
# ``AD`` is media that only ever existed as one, and ``STORY`` is gone in a
# day and does not appear on this edge anyway.
_PROMOTABLE_PRODUCTS: Final = frozenset({"FEED", "REELS"})

# A carousel is read as a picture on purpose. Meta answers the parent with
# one representative frame it chose itself, so the ad is a single image and
# nobody here picked which - see ``discovery.IG_MEDIA_DETAIL_FIELDS``.
_STILL_TYPES: Final = frozenset({"IMAGE", "CAROUSEL_ALBUM"})
_MOVING_TYPES: Final = frozenset({"VIDEO"})


def list_media(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[MediaDTO]:
    """Every image and video already uploaded to this ad account.

    Two calls, one list. Nothing is filtered out here: an advertiser
    looking for the picture they used last month should find it, and
    deciding on their behalf which of their own creatives are worth
    showing is not a decision this layer can make well.
    """
    graph = client or GraphClient(token=token)
    try:
        images = list_images(account_id=account_id, token=token, client=graph)
        videos = list_videos(account_id=account_id, token=token, client=graph)
    finally:
        if client is None:
            graph.close()

    # The one thing that *is* filtered, and it is not a judgement about the
    # picture: an image another account owns is listed here and cannot be
    # used by a creative made here - see :func:`belongs_to`.
    own = [row for row in images if belongs_to(row, account_id=account_id)]
    return [_image(row) for row in own] + [_video(row) for row in videos]


def describe_image(
    *, account_id: str, image_hash: str, token: str, client: GraphClient | None = None
) -> MediaDTO:
    """One image, read back by the hash an upload answered with.

    An upload returns the hash and nothing a screen can draw: the address,
    the size and the name are one more read away. When Meta lists nothing
    for the hash, the hash alone comes back - it is all a creative needs,
    and the next library sync fills in the rest.
    """
    for row in read_images(
        account_id=account_id, hashes=[image_hash], token=token, client=client
    ):
        if str(row.get("hash", "")) == image_hash and belongs_to(
            row, account_id=account_id
        ):
            return _image(row)
    return MediaDTO(kind=IMAGE, external_id=image_hash)


def own_image_hashes(
    *,
    account_id: str,
    hashes: list[str],
    token: str,
    client: GraphClient | None = None,
) -> frozenset[str]:
    """Which of these hashes are pictures this ad account itself holds.

    Asked before a creative is built, because Meta does not ask at that
    moment: a creative naming another account's hash is created, the ad
    under it is created, and the failure only arrives when delivery starts
    - "Image Not Found", on an ad the owner believes is running.

    A hash missing from the answer is not the account's. That covers both
    ways of not being one: a picture that was deleted, and a picture Meta
    lists on this account's edge while another account owns it.
    """
    wanted = [value for value in dict.fromkeys(hashes) if value]
    if not wanted:
        return frozenset()
    return frozenset(
        str(row.get("hash", ""))
        for row in read_images(
            account_id=account_id, hashes=wanted, token=token, client=client
        )
        if str(row.get("hash", "")) in wanted and belongs_to(row, account_id=account_id)
    )


def belongs_to(row: dict[str, Any], *, account_id: str) -> bool:
    """Whether one ``adimages`` row is this ad account's own picture.

    The edge answers with pictures other accounts own as well. On a live
    account two of twenty-two rows carried another owner, and every ad
    built on them failed with "Image Not Found". Such a row's ``id`` is
    ``<owner>:<hash>`` and its ``account_id`` is the same owner; the
    account's own rows read ``<this account's number>:<hash>``.

    The ``id`` is read first because it is the half seen on both kinds of
    row; ``account_id`` is the fallback for a row that came without one.
    A row that says neither is kept: silence is not a verdict, and
    treating it as one would empty a library over a field Meta stopped
    sending.
    """
    ident = str(row.get("id", ""))
    owner, colon, _ = ident.partition(":")
    if not colon:
        owner = str(row.get("account_id", ""))
    if not owner:
        return True
    return owner == account_id.removeprefix(_ACCOUNT_PREFIX)


def image_creatives(
    *, account_id: str, image_hash: str, token: str, client: GraphClient | None = None
) -> tuple[str, ...]:
    """The ids of every creative showing this image, ours or anybody's.

    Matched on the hash rather than trusted to be the only row: an edge
    that ignored the filter would answer with the whole library, and the
    first image's creatives would then be read as this one's.
    """
    for row in read_images(
        account_id=account_id,
        hashes=[image_hash],
        token=token,
        fields=IMAGE_USAGE_FIELDS,
        client=client,
    ):
        if str(row.get("hash", "")) == image_hash:
            return _ids(row.get("creatives"))
    return ()


def list_promotable_posts(
    *, page_id: str, token: str, client: GraphClient | None = None
) -> list[MediaDTO]:
    """The page's own posts, which can be promoted as they stand.

    Needs the **page** token. Listing the pages somebody administers and
    reading one page's content are different permissions on different
    objects, and Meta answers the second only to the second token.
    """
    graph = client or GraphClient(token=token)
    try:
        rows = list_page_posts(page_id=page_id, token=token, client=graph)
    finally:
        if client is None:
            graph.close()

    return [_post(row) for row in rows]


def list_instagram_media(
    *, ig_user_id: str, token: str, client: GraphClient | None = None
) -> list[MediaDTO]:
    """The Instagram account's own posts, as things an ad could be made of.

    Filtered here rather than by the caller, and the two rules it drops on
    are both silent failures otherwise.

    A post with no ``media_url`` is one Meta withheld the file for -
    licensed music, or a copyright flag - and there is nothing to fall back
    on. It is not rare: three posts in the first fifty of an ordinary
    account.

    A ``media_product_type`` outside feed and reels is media that was only
    ever an ad, which would be a strange thing to offer somebody as "your
    Instagram posts".

    What is **not** filtered here is eligibility. An ineligible post is
    carried out with its reason so a screen can show it greyed rather than
    silently missing: a picture somebody remembers posting and cannot find
    is a support conversation, and "you cannot use this one, here is why"
    is not.
    """
    graph = client or GraphClient(token=token)
    try:
        rows = list_instagram_media_rows(
            ig_user_id=ig_user_id, token=token, client=graph
        )
    finally:
        if client is None:
            graph.close()

    return _instagram_posts(rows)


def list_recent_instagram_media(
    *, ig_user_id: str, token: str, client: GraphClient | None = None
) -> list[MediaDTO]:
    """The newest page of :func:`list_instagram_media`, dropped on the
    same two rules. A part of the account, never the whole of it."""
    graph = client or GraphClient(token=token)
    try:
        rows = list_recent_instagram_media_rows(
            ig_user_id=ig_user_id, token=token, client=graph
        )
    finally:
        if client is None:
            graph.close()

    return _instagram_posts(rows)


def _instagram_posts(rows: list[dict[str, Any]]) -> list[MediaDTO]:
    parsed = [_instagram(row) for row in rows]
    return [item for item in parsed if item is not None]


def _instagram(row: dict[str, Any]) -> MediaDTO | None:
    """One post, or nothing if it cannot become an ad at all."""
    if str(row.get("media_product_type", "")) not in _PROMOTABLE_PRODUCTS:
        return None

    kind = _instagram_kind(str(row.get("media_type", "")))
    if kind is None:
        return None

    # The file. Absent means Meta withheld it, and a row with no file is a
    # thumbnail somebody can choose and nothing can upload.
    source = str(row.get("media_url", ""))
    if not source:
        return None

    # A still has no separate thumbnail on this edge - the file is the
    # picture. Stored to be *shown*, never to be uploaded from: it is a
    # signed URL that expires, and the launch reads a fresh one.
    still = str(row.get("thumbnail_url", "")) or source

    eligible, reason = _boost(row.get("boost_eligibility_info"))
    return MediaDTO(
        kind=kind,
        external_id=str(row.get("id", "")),
        name=str(row.get("caption", "")).strip(),
        thumbnail_url=still,
        permalink_url=str(row.get("permalink", "")),
        created_time=row.get("timestamp"),
        is_eligible=eligible,
        ineligible_reason=reason,
    )


def _instagram_kind(media_type: str) -> str | None:
    if media_type in _STILL_TYPES:
        return IG_IMAGE
    if media_type in _MOVING_TYPES:
        return IG_VIDEO
    return None


def _boost(info: object) -> tuple[bool | None, str]:
    """Meta's own verdict, or silence.

    Silence is not a refusal. A field Meta did not send is one it was not
    asked or could not answer, and treating that as "no" would empty a
    picker over an API version change.
    """
    if not isinstance(info, dict):
        return None, ""
    verdict = info.get("eligible_to_boost")
    if not isinstance(verdict, bool):
        return None, ""
    return verdict, str(info.get("boost_ineligible_reason", ""))


def _image(row: dict[str, Any]) -> MediaDTO:
    """``hash``, not ``id``. See the module docstring."""
    return MediaDTO(
        kind=IMAGE,
        external_id=str(row.get("hash", "")),
        name=str(row.get("name", "")),
        thumbnail_url=str(row.get("url", "")),
        permalink_url=str(row.get("permalink_url", "")),
        width=_as_int(row.get("width")),
        height=_as_int(row.get("height")),
        created_time=row.get("created_time"),
    )


def _video(row: dict[str, Any]) -> MediaDTO:
    return MediaDTO(
        kind=VIDEO,
        external_id=str(row.get("id", "")),
        name=str(row.get("title") or row.get("description") or ""),
        thumbnail_url=str(row.get("picture", "")),
        permalink_url=str(row.get("source", "")),
        created_time=row.get("created_time"),
    )


def _post(row: dict[str, Any]) -> MediaDTO:
    """A post's own text is its name. It is what a person recognises it by,
    and Meta gives posts no title of any kind."""
    message = str(row.get("message", "")).strip()
    return MediaDTO(
        kind=POST,
        external_id=str(row.get("id", "")),
        name=message,
        thumbnail_url=str(row.get("full_picture", "")),
        permalink_url=str(row.get("permalink_url", "")),
        created_time=row.get("created_time"),
    )


def _ids(value: object) -> tuple[str, ...]:
    """A list of ids, whether Meta sent them bare or inside objects."""
    if not isinstance(value, list):
        return ()
    found: list[str] = []
    for item in value:
        ident = item.get("id", "") if isinstance(item, dict) else item
        if ident:
            found.append(str(ident))
    return tuple(found)


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0
