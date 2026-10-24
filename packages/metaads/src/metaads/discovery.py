"""The reads that answer "what is available", before anything is built."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from metaads.client import GraphClient

INTEREST_FIELDS: Final = (
    "id,name,audience_size_lower_bound,audience_size_upper_bound,path,topic"
)

IMAGE_FIELDS: Final = "hash,name,url,permalink_url,width,height,created_time,account_id"
IMAGE_USAGE_FIELDS: Final = "hash,creatives"
VIDEO_FIELDS: Final = "id,title,description,picture,source,created_time,length"
POST_FIELDS: Final = "id,message,created_time,full_picture,permalink_url"
CREATIVE_FIELDS: Final = "id,name,object_story_spec,thumbnail_url,status"

IG_MEDIA_FIELDS: Final = (
    "id,caption,media_type,media_product_type,media_url,permalink,"
    "thumbnail_url,timestamp,boost_eligibility_info"
)

IG_MEDIA_DETAIL_FIELDS: Final = (
    f"{IG_MEDIA_FIELDS},username,is_shared_to_feed,"
    "children{id,media_type,media_url,thumbnail_url}"
)

PAGE_SIZE: Final = 50

IG_MEDIA_PAGES: Final = 200

PIXEL_FIELDS: Final = (
    "id,name,last_fired_time,is_unavailable,creation_time,data_use_setting,"
    "enable_automatic_matching,owner_business"
)

SEARCH_LIMIT: Final = 25


def search_interests(
    *, query: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Interests whose name matches ``query``."""
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adinterest",
            q=query,
            limit=SEARCH_LIMIT,
            fields=INTEREST_FIELDS,
        )
    return list(payload.get("data", []))


LOCATION_FIELDS: Final = (
    "key,name,type,country_code,country_name,region,region_id,"
    "supports_region,supports_city"
)

LOCATION_TYPES: Final[tuple[str, ...]] = ("city", "region", "country")


def search_locations(
    *,
    query: str,
    token: str,
    location_types: tuple[str, ...] = LOCATION_TYPES,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Places whose name matches ``query``."""
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adgeolocation",
            q=query,
            location_types=_json_list(list(location_types)),
            limit=SEARCH_LIMIT,
            fields=LOCATION_FIELDS,
        )
    return list(payload.get("data", []))


TRAIT_CLASSES: Final[dict[str, str]] = {
    "behaviour": "behaviors",
    "life_event": "life_events",
}

CATEGORY_FIELDS: Final = (
    "id,name,type,audience_size_lower_bound,audience_size_upper_bound,path"
)

CATEGORY_PAGE: Final = 100


def browse_traits(
    *, klass: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Every row Meta publishes in one detailed-targeting class."""
    reserved: dict[str, Any] = {"class": klass}
    with _session(client, token) as graph:
        return graph.get_all(
            "search",
            type="adTargetingCategory",
            **reserved,
            limit=CATEGORY_PAGE,
            fields=CATEGORY_FIELDS,
        )


def suggest_interests(
    *, names: list[str], token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Interests Meta considers adjacent to the ones already chosen."""
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adinterestsuggestion",
            interest_list=_json_list(names),
            limit=SEARCH_LIMIT,
            fields=INTEREST_FIELDS,
        )
    return list(payload.get("data", []))


def validate_interests(
    *, names: list[str], token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Whether Meta still recognises these names, in one call."""
    with _session(client, token) as graph:
        payload = graph.get(
            "search",
            type="adinterestvalid",
            interest_list=_json_list(names),
            fields=INTEREST_FIELDS,
        )
    return list(payload.get("data", []))


def list_images(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Images already uploaded to this ad account."""
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/adimages", fields=IMAGE_FIELDS, limit=PAGE_SIZE
        )


def read_images(
    *,
    account_id: str,
    hashes: list[str],
    token: str,
    fields: str = IMAGE_FIELDS,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Named images on this ad account, rather than all of them."""
    with _session(client, token) as graph:
        payload = graph.get(
            f"{account_id}/adimages", hashes=_json_list(hashes), fields=fields
        )
    return [row for row in payload.get("data", []) if isinstance(row, dict)]


def list_videos(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/advideos", fields=VIDEO_FIELDS, limit=PAGE_SIZE
        )


def list_creatives(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """Whole creatives from previous campaigns, reusable as they are."""
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/adcreatives", fields=CREATIVE_FIELDS, limit=PAGE_SIZE
        )


def list_page_posts(
    *, page_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """The page's own posts, which can be promoted without a new creative."""
    with _session(client, token) as graph:
        return graph.get_all(f"{page_id}/posts", fields=POST_FIELDS, limit=PAGE_SIZE)


def list_instagram_media(
    *,
    ig_user_id: str,
    token: str,
    fields: str = IG_MEDIA_FIELDS,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """The Instagram account's own posts, newest first."""
    with _session(client, token) as graph:
        return graph.get_all(
            f"{ig_user_id}/media",
            fields=fields,
            limit=PAGE_SIZE,
            max_pages=IG_MEDIA_PAGES,
        )


def list_recent_instagram_media(
    *,
    ig_user_id: str,
    token: str,
    fields: str = IG_MEDIA_FIELDS,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """The newest page of the same edge, and nothing past it."""
    with _session(client, token) as graph:
        payload = graph.get(f"{ig_user_id}/media", fields=fields, limit=PAGE_SIZE)
    rows = payload.get("data", [])
    return list(rows) if isinstance(rows, list) else []


def read_instagram_media(
    *,
    media_id: str,
    token: str,
    fields: str = IG_MEDIA_DETAIL_FIELDS,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """One post, with everything worth asking it for."""
    with _session(client, token) as graph:
        return graph.get(media_id, fields=fields)


def read_media_insight(
    *,
    media_id: str,
    metric: str,
    token: str,
    client: GraphClient | None = None,
) -> int | None:
    """One insight figure for one Instagram post, or ``None`` if not given."""
    with _session(client, token) as graph:
        payload = graph.get(f"{media_id}/insights", metric=metric)
    for row in payload.get("data", []):
        total = (row.get("total_value") or {}).get("value")
        if isinstance(total, int):
            return total
        values = row.get("values") or []
        if values and isinstance(values[0].get("value"), int):
            return int(values[0]["value"])
    return None


def list_pixels(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[dict[str, Any]]:
    """The account's conversion pixels, raw."""
    with _session(client, token) as graph:
        return graph.get_all(
            f"{account_id}/adspixels", fields=PIXEL_FIELDS, limit=PAGE_SIZE
        )


def estimate_reach(
    *,
    account_id: str,
    targeting: dict[str, Any],
    optimization_goal: str,
    token: str,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """How many people this spec would reach, before anything is created."""
    with _session(client, token) as graph:
        payload = graph.get(
            f"{account_id}/delivery_estimate",
            optimization_goal=optimization_goal,
            targeting_spec=_json_value(targeting),
        )
    rows = payload.get("data", [])
    return dict(rows[0]) if rows else {}


def _json_list(values: list[str]) -> str:
    """Meta takes list parameters as a JSON array in a query string."""
    return _json_value(values)


def _json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@contextmanager
def _session(client: GraphClient | None, token: str) -> Iterator[GraphClient]:
    """One connection, closed only if this module opened it."""
    graph = client or GraphClient(token=token)
    try:
        yield graph
    finally:
        if client is None:
            graph.close()
