"""What one look at a web page found."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

Outcome = Literal[
    "ok",
    "not_found",
    "http_error",
    "no_such_host",
    "refused",
    "timeout",
    "tls_error",
    "blocked",
    "too_many_redirects",
    "unreachable",
]

# The outcomes that mean the page is gone for every visitor, not only for
# this checker.
#
# Deliberately short. A site behind bot protection answers a script with 403
# or 503 and opens for a person; a timeout can be this server's own network;
# a certificate problem can be a missing intermediate on our side. Refusing
# a campaign on any of those would stop working adverts. What is left is a
# name that does not exist, a machine that refuses the connection outright,
# and a page the site itself says is not there.
DOWN_FOR_EVERYONE: Final[frozenset[str]] = frozenset(
    {"no_such_host", "refused", "not_found"}
)


class SiteProbe(BaseModel):
    """One page, looked at once.

    ``meta_pixel_ids`` is what the HTML says and no more. A pixel loaded
    through a tag manager is not in the HTML at all, which is why
    ``has_tag_manager`` is reported beside it: an empty list next to a tag
    manager is "cannot tell", not "none".
    """

    model_config = ConfigDict(frozen=True)

    url: str
    final_url: str = ""
    outcome: Outcome
    status_code: int = 0
    meta_pixel_ids: tuple[str, ...] = ()
    has_tag_manager: bool = False

    @property
    def is_down(self) -> bool:
        """Whether nobody at all can open this page."""
        return self.outcome in DOWN_FOR_EVERYONE
