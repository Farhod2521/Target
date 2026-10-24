"""What an advertiser already has, ready to be put in an ad."""

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

_ACCOUNT_PREFIX: Final = "act_"

IG_IMAGE: Final = "ig_image"
IG_VIDEO: Final = "ig_video"

_PROMOTABLE_PRODUCTS: Final = frozenset({"FEED", "REELS"})

_STILL_TYPES: Final = frozenset({"IMAGE", "CAROUSEL_ALBUM"})
_MOVING_TYPES: Final = frozenset({"VIDEO"})


def list_media(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[MediaDTO]:
    """Every image and video already uploaded to this ad account."""
    graph = client or GraphClient(token=token)
    try:
        images = list_images(account_id=account_id, token=token, client=graph)
        videos = list_videos(account_id=account_id, token=token, client=graph)
    finally:
        if client is None:
            graph.close()

    own = [row for row in images if belongs_to(row, account_id=account_id)]
    return [_image(row) for row in own] + [_video(row) for row in videos]


def describe_image(
    *, account_id: str, image_hash: str, token: str, client: GraphClient | None = None
) -> MediaDTO:
    """One image, read back by the hash an upload answered with."""
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
    """Which of these hashes are pictures this ad account itself holds."""
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
    """Whether one ``adimages`` row is this ad account's own picture."""
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
    """The ids of every creative showing this image, ours or anybody's."""
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
    """The page's own posts, which can be promoted as they stand."""
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
    """The Instagram account's own posts, as things an ad could be made of."""
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

    source = str(row.get("media_url", ""))
    if not source:
        return None

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
    """Meta's own verdict, or silence."""
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
