"""Audiences the advertiser owns, and the three ways one gets filled."""

from core.audiences.exceptions import (
    ActionNotSupported,
    AudienceRuleError,
    BreadthNotOffered,
    CountryUnknown,
    RetentionNotOffered,
    RetentionTooLong,
    SourceNotSupported,
)
from core.audiences.lookalikes import BREADTHS, build_lookalike
from core.audiences.members import (
    COUNTRY_CODE_LENGTH,
    CustomerRecord,
    hashed_member,
    hashed_members,
)
from core.audiences.rules import WINDOWS, build_rule, windows_for

__all__ = [
    "BREADTHS",
    "COUNTRY_CODE_LENGTH",
    "WINDOWS",
    "ActionNotSupported",
    "AudienceRuleError",
    "BreadthNotOffered",
    "CountryUnknown",
    "CustomerRecord",
    "RetentionNotOffered",
    "RetentionTooLong",
    "SourceNotSupported",
    "build_lookalike",
    "build_rule",
    "hashed_member",
    "hashed_members",
    "windows_for",
]
