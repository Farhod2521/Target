"""The Instagram professional account behind a page, as its owner sees it.

Its own module rather than a row beside ``InstagramAccountDTO``, because the
two answer different questions. That one is what an ad creative needs - an
id and a handle to recognise it by - and it arrives inside the page list.
This one is the profile itself, read from ``/{ig-user-id}``, and it exists
so that a screen can show somebody the account they connected the way their
own phone shows it: picture, name, biography and the three counts.
"""

from pydantic import field_validator

from metaads.dto_base import MetaDTO, _text


class InstagramProfileDTO(MetaDTO):
    """One Instagram profile, every field optional but the id.

    Optional because Meta decides per account what it answers with. A
    profile with no biography omits the key rather than sending an empty
    one, and an account that exists only through its page answers with a
    handful of fields - both are ordinary, and neither is a shape change.

    **The counts are ``None`` when Meta did not send them**, never nought.
    An account with no followers and an answer that left the count out are
    different facts, and a screen printing "0 followers" for the second is
    telling its owner something false about their own business.
    """

    id: str
    username: str = ""
    name: str = ""
    biography: str = ""
    website: str = ""
    profile_picture_url: str = ""
    followers_count: int | None = None
    follows_count: int | None = None
    media_count: int | None = None

    @field_validator(
        "username",
        "name",
        "biography",
        "website",
        "profile_picture_url",
        mode="before",
    )
    @classmethod
    def _strings(cls, value: object) -> str:
        """A ``null`` or a number where text belongs reads as no text.

        A profile name is whatever its owner typed, and one that is only
        digits must not fail the whole read over its type.
        """
        return _text(value)

    @field_validator("followers_count", "follows_count", "media_count", mode="before")
    @classmethod
    def _counts(cls, value: object) -> int | None:
        """A whole number, or unknown. Never a guess."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None
