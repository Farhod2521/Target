"""Custom audiences and their uploads, as Meta answers them."""

import json
from datetime import datetime
from typing import Any, Final

from pydantic import Field, field_validator

from metaads.dto_base import MetaDTO

RAW_KEY: Final = "raw"

_MEMBER_SUBTYPES: Final[frozenset[str]] = frozenset({"CUSTOM"})

_SEEDLESS_SUBTYPES: Final[frozenset[str]] = frozenset({"LOOKALIKE"})

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
    customer_file_source: str = ""

    approximate_count_lower_bound: int = -1
    approximate_count_upper_bound: int = -1

    operation_status: AudienceStateRow = Field(default_factory=AudienceStateRow)
    delivery_status: AudienceStateRow = Field(default_factory=AudienceStateRow)
    data_source: CustomAudienceDataSourceRow = Field(
        default_factory=CustomAudienceDataSourceRow
    )

    rule: dict[str, Any] = Field(default_factory=dict)
    lookalike_spec: dict[str, Any] = Field(default_factory=dict)
    retention_days: int = 0

    time_created: datetime | None = None
    time_updated: datetime | None = None

    @field_validator("rule", "lookalike_spec", mode="before")
    @classmethod
    def _as_document(cls, value: object) -> object:
        """Meta's two documents, whichever of the two shapes they arrive in."""
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
        """The lower bound, with Meta's "still counting" turned into zero."""
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
