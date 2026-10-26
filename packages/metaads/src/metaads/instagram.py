"""Reading an Instagram professional account's own profile.

``/{ig-user-id}`` on ``graph.facebook.com``: the Facebook-Login half of the
Instagram Platform, reached with the page token already in hand for the
media edge. Meta lists ``instagram_basic`` and ``pages_read_engagement`` as
what it needs, and both are asked for on the consent screen.

Two functions for one call, the same split the media edge has. The raw one
is for the console, where the shape is looked at before anything is built
on it; the parsed one is for the product.
"""

from typing import Any, Final

from metaads.client import GraphClient
from metaads.instagram_rows import InstagramProfileDTO
from metaads.parsing import parsed

# What a profile is asked for. Everything a person would recognise their
# account by, and nothing that counts other people: ``business_discovery``
# and the insights edges are different permissions for different products.
#
# ``website`` is here because the biography often says "link below" and a
# card showing one without the other reads as a clipped sentence.
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
    """The profile, raw.

    ``fields`` is a parameter so the console can bisect a refusal: Meta
    answers ``#100`` for the whole request over one name it does not
    recognise, and an account that exists only through its page is
    documented as answering with fewer fields than the others.
    """
    graph = client or GraphClient(token=token)
    try:
        return graph.get(ig_user_id, fields=fields)
    finally:
        if client is None:
            graph.close()


def read_instagram_profile(
    *, ig_user_id: str, token: str, client: GraphClient | None = None
) -> InstagramProfileDTO:
    """The profile, as the product reads it.

    ``profile_picture_url`` is a signed address that expires, like every
    file on Meta's CDN. It is fine to show for as long as it lasts and must
    not be treated as the picture's permanent home - the next read brings a
    fresh one.
    """
    row = read_instagram_account(ig_user_id=ig_user_id, token=token, client=client)
    return parsed(InstagramProfileDTO, row)
