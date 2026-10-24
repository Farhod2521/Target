"""Which Facebook page a piece of advertising speaks as."""

from typing import Any

POST_ID_SEPARATOR = "_"


def page_of_promoted(promoted: Any) -> str:
    """The page a group promotes, as the provider's own object names it."""
    if not isinstance(promoted, dict):
        return ""
    page = promoted.get("page_id")
    return (
        str(page) if isinstance(page, str | int) and not isinstance(page, bool) else ""
    )


def page_of_post(post_external_id: str) -> str:
    """The page half of a post's id, or nothing when it is not one."""
    page, separator, _rest = str(post_external_id).partition(POST_ID_SEPARATOR)
    return page if separator and page.isdigit() else ""


__all__ = ["POST_ID_SEPARATOR", "page_of_post", "page_of_promoted"]
