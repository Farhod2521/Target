"""Custom audiences and their uploads, as Meta answers them."""

import json
from datetime import datetime
from typing import Any, Final

from pydantic import Field, field_validator

from metaads.dto_base import MetaDTO

# Where an answer that would not parse is kept, when Meta sends a document
# this package cannot read. One key, so the column stays truthy - "there is
# a document here" is the only question anything asks of these two fields -
# and the text survives for whoever has to find out what arrived.
RAW_KEY: Final = "raw"

# The subtypes Meta will accept a customer list into. ``CUSTOM`` is what
# this product creates; the rest are audiences Meta fills in itself and
# would refuse an upload.
#
# Not an exhaustive list of subtypes and deliberately not one. Meta has
# twenty-odd, they are added to, and the only question asked here is
# whether people may be uploaded - so an unfamiliar word answers "no",
# which is the safe direction: the cost is an upload button that does not
# appear, against personal data posted to an audience never meant to hold
# any.
_MEMBER_SUBTYPES: Final[frozenset[str]] = frozenset({"CUSTOM"})

# The subtypes no new audience may be built to resemble.
#
# The mirror image of the set above, and deliberately not its complement.
# An audience Meta fills in itself takes no upload and makes a perfectly
# good seed, so "cannot be uploaded into" and "cannot be built from" are
# different questions with different answers.
#
# One entry: an audience that is already a lookalike. Meta names three
# things a lookalike may be built out of - a custom audience, campaign
# conversions, page fans - and another lookalike is not among them. An
# undocumented combination is one this package does not offer, which is the
# same bet it declined to take on video.
#
# An unfamiliar subtype is therefore allowed through, the opposite
# direction from the set above. Nothing personal moves either way here, so
# the cost of a wrong yes is one refusal that names itself, against a row
# missing from a picker with nothing to explain it.
_SEEDLESS_SUBTYPES: Final[frozenset[str]] = frozenset({"LOOKALIKE"})

# Meta's delivery_status code for "this audience is ready for use".
#
# One value and not a table. The full vocabulary is unpublished - the two
# documented codes mean ready and disabled, and the rest are met rather
# than looked up - so anything else reads as "not ready yet", which is both
# the honest answer and the safe one. The code and Meta's own sentence
# travel whole beside it for whoever has to find out what an unfamiliar one
# meant.
_DELIVERY_READY: Final = 200


class AudienceStateRow(MetaDTO):
    """Meta's ``{code, description}`` pair, used for two different states.

    ``operation_status`` says whether the last write has finished being
    processed; ``delivery_status`` says whether the result may be
    advertised to. Same shape, different questions, and an audience is
    routinely one and not the other - a finished upload that produced too
    few people is done and unusable at once.
    """

    code: int = 0
    description: str = ""


class CustomAudienceDataSourceRow(MetaDTO):
    """Where Meta says the audience came from, in its own two-part word.

    Kept whole and unread. It is Meta's record of how the data was
    gathered, it is shown in its own console beside the audience, and the
    only reason to carry it is so an operator comparing the two screens is
    not looking at a field that exists on one of them.
    """

    type: str = ""
    sub_type: str = ""


class CustomAudienceRow(MetaDTO):
    """One row of ``/act_<id>/customaudiences``.

    Three things about this shape are worth knowing before reading the
    parser, and all three are places a guess would have been wrong.

    **The count is a range, and the single figure is gone.**
    ``approximate_count`` was retired; Meta answers
    ``approximate_count_lower_bound`` and its upper twin, exactly as it did
    when it retired ``audience_size`` on the interest catalogue. Both are
    ``-1`` while it is still counting - not zero, and not absent - which is
    the one value that would read as "this audience is empty" if it were
    passed straight on.

    **The timestamps are unix integers.** Everywhere else in this package
    Meta answers ISO strings under ``created_time``; here it answers
    seconds since the epoch under ``time_created``. Pydantic reads an
    integer into a ``datetime`` as a unix timestamp, so this works - but it
    works by accident unless somebody knows, and the field names differ too.

    **Two statuses, and neither is a status vocabulary this package owns.**
    See :class:`AudienceStateRow`.
    """

    id: str
    name: str = ""
    description: str = ""
    subtype: str = ""
    # How the advertiser says they got the data - ``USER_PROVIDED_ONLY`` and
    # its two siblings. Sent at creation and read back here, because it is
    # part of the representation they made about their own list.
    customer_file_source: str = ""

    approximate_count_lower_bound: int = -1
    approximate_count_upper_bound: int = -1

    operation_status: AudienceStateRow = Field(default_factory=AudienceStateRow)
    delivery_status: AudienceStateRow = Field(default_factory=AudienceStateRow)
    data_source: CustomAudienceDataSourceRow = Field(
        default_factory=CustomAudienceDataSourceRow
    )

    # What Meta gathers people by, for the audiences it fills itself.
    # Empty on a customer list. Carried whole and never parsed back into a
    # domain object: most of these were built in Ads Manager with the whole
    # of Meta's vocabulary - nested conditions, sources this product does
    # not offer, exclusions - and a parser would have to understand all of
    # it or quietly drop what it did not.
    rule: dict[str, Any] = Field(default_factory=dict)
    # What Meta was told to build this one to resemble. Present only on a
    # lookalike, and Meta says of it only that it is "generated" for that
    # subtype - the shape of what comes back is not documented anywhere.
    # Carried whole for that reason: an undocumented answer kept intact is
    # the one way to read it later without a guess having been made now.
    #
    # It does not contain the seed. ``origin_audience_id`` is a creation
    # parameter and not a readable field, so a lookalike built in Ads
    # Manager arrives with its ratio and its country and no origin at all.
    lookalike_spec: dict[str, Any] = Field(default_factory=dict)
    # How long somebody stays in it. Zero on a customer list, which has no
    # window: the people in one stay until they are taken out.
    retention_days: int = 0

    time_created: datetime | None = None
    time_updated: datetime | None = None

    @field_validator("rule", "lookalike_spec", mode="before")
    @classmethod
    def _as_document(cls, value: object) -> object:
        """Meta's two documents, whichever of the two shapes they arrive in.

        **The Custom Audience node declares ``rule`` as a ``string``** - a
        JSON document serialised into one - while the objects Meta actually
        answers with have been seen both ways, and ``lookalike_spec`` is
        declared as an object and sits beside it in the same payload. So
        the shape is not something this package can know in advance, and it
        must not be something it bets the account on.

        **What the bet would have cost is the reason this exists.** These
        fields are read through :func:`metaads.parsing.parsed_all`, which is
        all-or-nothing by design: one row that will not fit takes the whole
        page with it. A single audience somebody built in Ads Manager -
        which is exactly the row carrying a ``rule`` - would therefore have
        stopped the account's entire audience list from being read, and the
        sync above it swallows that failure into a log line. Nothing on any
        screen would have said why the list stopped moving.

        A document that cannot be read at all is kept as text under
        :data:`RAW_KEY` rather than dropped. Nothing in this project parses
        either field - they are carried whole as evidence - so the only
        question ever asked of them is whether there is one, and an empty
        dict would answer that wrongly for a row that plainly has one.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return {}
        try:
            parsed_value = json.loads(text)
        except ValueError:
            return {RAW_KEY: text}
        return parsed_value if isinstance(parsed_value, dict) else {RAW_KEY: text}

    @property
    def accepts_members(self) -> bool:
        """Whether people may be uploaded into this one. See
        :data:`_MEMBER_SUBTYPES`."""
        return self.subtype.strip().upper() in _MEMBER_SUBTYPES

    @property
    def can_seed(self) -> bool:
        """Whether a new audience may be built to resemble this one. See
        :data:`_SEEDLESS_SUBTYPES`."""
        return self.subtype.strip().upper() not in _SEEDLESS_SUBTYPES

    @property
    def is_ready(self) -> bool:
        """Whether an ad set may be aimed at this audience today."""
        return self.delivery_status.code == _DELIVERY_READY

    @property
    def count_lower(self) -> int:
        """The lower bound, with Meta's "still counting" turned into zero.

        Meta answers ``-1`` for both bounds until it has finished, and a
        negative number of people is not something any screen should have to
        defend against. Zero here means "not said yet", which is what the
        DTO above documents and what a screen shows as a dash rather than as
        an empty audience.
        """
        return max(self.approximate_count_lower_bound, 0)

    @property
    def count_upper(self) -> int:
        return max(self.approximate_count_upper_bound, 0)


class MemberUploadRow(MetaDTO):
    """What Meta answers after a customer list has been posted.

    ``num_invalid_entries`` is the field this row exists for. A
    normalisation rule applied wrongly does not produce an error - it
    produces digests of the wrong thing, which are the right shape and
    match nobody - and this number is the only warning that arrives while
    the upload is still on the screen.

    ``invalid_entry_samples`` carries a few of the refused rows with Meta's
    reason. What is in them is already hashed, and it stays that way: this
    package never holds a person and does not begin to here.
    """

    audience_id: str = ""
    session_id: str = ""
    num_received: int = 0
    num_invalid_entries: int = 0
    invalid_entry_samples: dict[str, str] = Field(default_factory=dict)

    @field_validator("session_id", "audience_id", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> object:
        """Meta answers the session id as a number and the audience id as a
        string, in the same object. The same inconsistency
        :class:`AdAccountDTO` meets over money, met again."""
        if value is None:
            return ""
        return str(value) if isinstance(value, int | float) else value
