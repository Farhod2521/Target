"""What gets appended to the advertiser's own address when somebody taps."""

from typing import Final

# ``utm_term`` carries the ad set's id: a sign-up that brings it back is tied
# to its campaign even after the campaign is renamed (a name is all
# ``utm_campaign`` says, and a name changes).
DEFAULT_TAGS: Final = (
    "utm_source={{site_source_name}}"
    "&utm_medium=paid_social"
    "&utm_campaign={{campaign.name}}"
    "&utm_content={{ad.name}}"
    "&utm_term={{adset.id}}"
)

FORBIDDEN: Final[frozenset[str]] = frozenset({"?", "#", " ", "\t", "\n"})


def clean_tags(text: str) -> str:
    """The string as it should be stored: trimmed, without its leading join."""
    return text.strip().lstrip("?&").rstrip("&")


def tags_are_usable(text: str) -> bool:
    """Whether this is a query the provider can append to an address."""
    cleaned = clean_tags(text)
    if not cleaned:
        return True
    if any(char in cleaned for char in FORBIDDEN):
        return False
    return all(pair.split("=", 1)[0] for pair in cleaned.split("&"))


__all__ = ["DEFAULT_TAGS", "FORBIDDEN", "clean_tags", "tags_are_usable"]
