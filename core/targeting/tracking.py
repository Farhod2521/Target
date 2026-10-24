"""What gets appended to the advertiser's own address when somebody taps.

An advertiser with a website already has a tool telling them where their
visitors came from, and without this every visit an advert buys arrives in
that tool as "facebook" at best and as nothing at all at worst. The tags
are what let them see that this campaign, and this advert inside it,
brought the people who then bought something - which is the one figure
this product cannot show them, because it happens on their side.

**Two vocabularies in one string, and only one of them is the provider's.**
``utm_source`` and its siblings are a convention of whatever is reading
them - an analytics tool, a shop's own admin - and mean nothing to the
provider. The braces are the provider's: it substitutes ``{{campaign.name}}``
and the rest as the advert is served, so the tags describe the advert that
was actually shown without anybody writing the name twice.

Kept as one opaque string rather than a set of fields. What an advertiser's
analytics wants is its own business - some read ``utm_*``, some read their
own names - and a screen offering five labelled boxes would be a screen
that cannot express the sixth thing somebody needs.
"""

from typing import Final

# What a website campaign carries unless the owner says otherwise.
#
# The source is the provider's own placeholder rather than the word
# "facebook": one advert runs on several surfaces and an advertiser reading
# "facebook" beside a visit that came from Instagram is being told something
# untrue. The campaign and advert names are ours, built in
# ``apps.ads.naming``, and readable in a report without a lookup.
#
# No ``utm_term``: it is a search advertiser's field, and a placement name
# in it reads as a keyword nobody bid on.
DEFAULT_TAGS: Final = (
    "utm_source={{site_source_name}}"
    "&utm_medium=paid_social"
    "&utm_campaign={{campaign.name}}"
    "&utm_content={{ad.name}}"
)

# What may not be in the string. The provider appends it to an address that
# may already carry a query of its own, so the caller supplies pairs and
# never the punctuation that joins them - a second ``?`` makes the whole
# tail part of the previous value, silently, and the visit arrives
# unattributed rather than misattributed.
FORBIDDEN: Final[frozenset[str]] = frozenset({"?", "#", " ", "\t", "\n"})


def clean_tags(text: str) -> str:
    """The string as it should be stored: trimmed, without its leading join.

    Somebody pasting from a browser's address bar brings the ``?`` or the
    ``&`` with them, and both are the provider's to add.
    """
    return text.strip().lstrip("?&").rstrip("&")


def tags_are_usable(text: str) -> bool:
    """Whether this is a query the provider can append to an address.

    Empty is usable and means "send the address as it is", which is what
    every campaign built before this question existed does.

    Deliberately shallow: whether ``utm_campaign`` is the right name for
    what somebody's analytics reads is their question, not this package's.
    What is checked is only that the string is a query tail - pairs joined
    by ``&``, each with a name - because everything else here is opaque on
    purpose.
    """
    cleaned = clean_tags(text)
    if not cleaned:
        return True
    if any(char in cleaned for char in FORBIDDEN):
        return False
    return all(pair.split("=", 1)[0] for pair in cleaned.split("&"))


__all__ = ["DEFAULT_TAGS", "FORBIDDEN", "clean_tags", "tags_are_usable"]
