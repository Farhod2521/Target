"""Reading an Instagram professional account's own profile."""

from typing import Any, Final

from metaads.client import GraphClient
from metaads.instagram_rows import InstagramProfileDTO
from metaads.parsing import parsed

IG_PROFILE_FIELDS: Final = (
    "id,username,name,biography,website,profile_picture_url,"
    "followers_count,follows_count,media_count"
)


def read_instagram_account(
    *,
    ig_user_id: str,
    token: str,
    fields: str = IG_PROFILE_FIELDS,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """The profile, raw."""
    graph = client or GraphClient(token=token)
    try:
        return graph.get(ig_user_id, fields=fields)
    finally:
        if client is None:
            graph.close()


def read_instagram_profile(
    *, ig_user_id: str, token: str, client: GraphClient | None = None
) -> InstagramProfileDTO:
    """The profile, as the product reads it."""
    row = read_instagram_account(ig_user_id=ig_user_id, token=token, client=client)
    return parsed(InstagramProfileDTO, row)
