"""Which Facebook page a piece of advertising speaks as.

The subscription is sold per page and the provider never says so in a
figure, so every reader that has to place money asks the same two
questions of whatever the provider handed it. They are here rather than
beside one of those readers because there are two kinds: one reads the
mirror, the other reads the provider's answer directly, and a rule with
two copies is a rule that is true in two different ways the day one of
them is corrected.

Both answer with a page id or with nothing. Nothing is not a failure -
a group that promotes a pixel declares no page and never will - and the
caller decides what unplaced money means to it.
"""

from typing import Any

# How the provider spells a post's id: the page, an underscore, the post.
POST_ID_SEPARATOR = "_"


def page_of_promoted(promoted: Any) -> str:
    """The page a group promotes, as the provider's own object names it.

    The strongest evidence there is: a group collecting enquiries says
    where they land, and it says it as a declaration rather than as
    something inferred from the adverts underneath it.

    Typed as :data:`~typing.Any` because it is read out of a column that
    holds whatever the provider sent. A dict is what it should be, and
    anything else is answered with nothing rather than raised over - the
    caller is placing money, not validating a schema.
    """
    if not isinstance(promoted, dict):
        return ""
    page = promoted.get("page_id")
    return (
        str(page) if isinstance(page, str | int) and not isinstance(page, bool) else ""
    )


def page_of_post(post_external_id: str) -> str:
    """The page half of a post's id, or nothing when it is not one.

    A creative promoting a post that already existed carries no page
    block at all - its words and its author live on the post - and the
    only place the page survives is the first half of the post's own id.
    """
    page, separator, _rest = str(post_external_id).partition(POST_ID_SEPARATOR)
    return page if separator and page.isdigit() else ""


__all__ = ["POST_ID_SEPARATOR", "page_of_post", "page_of_promoted"]
