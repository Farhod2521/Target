"""The barrier that keeps a lead's details out of a prompt."""

from dataclasses import fields

from core.chat.context import (
    AccountDigest,
    AudienceDigest,
    BusinessDigest,
    CampaignDigest,
    ChatContext,
    SuggestionDigest,
    TotalsDigest,
)
from core.chat.rungs import AdDigest, AdSetDigest, FormDigest, PageDigest

# Words that would name a person rather than a measurement. The list is the
# test: a field called any of these is a field somebody could put a lead in.
# "answer" is here because a form's digest sits next to what people wrote
# into it: the questions travel, the answers never do.
PERSONAL = (
    "phone",
    "email",
    "full_name",
    "first_name",
    "last_name",
    "address",
    "answer",
)

DIGESTS = (
    BusinessDigest,
    TotalsDigest,
    CampaignDigest,
    AdSetDigest,
    AdDigest,
    FormDigest,
    PageDigest,
    AudienceDigest,
    SuggestionDigest,
    AccountDigest,
)


def test_no_digest_has_anywhere_to_put_a_person() -> None:
    """The structural half of "chat never sees lead PII".

    Not a prompt rule and not a filter over the rendered text: the shape
    has no field for it, so adding one means editing this list and saying
    why in review. Same barrier ``AudienceMemberDTO`` puts in front of
    plain-text personal data, for the same reason.
    """
    for digest in DIGESTS:
        for item in fields(digest):
            assert not any(word in item.name for word in PERSONAL), (
                f"{digest.__name__}.{item.name} could hold a person"
            )


def test_a_visitor_gets_no_account_at_all() -> None:
    """Not an empty digest - none. There is nothing to leak by accident."""
    context = ChatContext(account=None)

    assert context.render() == ""
    assert context.figures() == frozenset()
