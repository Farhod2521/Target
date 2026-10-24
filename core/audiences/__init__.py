"""Audiences the advertiser owns, and the three ways one gets filled.

Three jobs, and the first is the odd one. :mod:`core.audiences.members` turns
people this business holds into digests a provider will match on - the one
place personal data is prepared to leave this system.
:mod:`core.audiences.rules` describes people the provider already knows
about, and touches no personal data at all.
:mod:`core.audiences.lookalikes` names an audience that already exists and
asks for more people like the ones in it - not even the seed's contents
move, only its id.

All three are here rather than in a provider package for the same reason,
arrived at three times: the phone parser lives on this side of the
boundary, the rule envelope is a provider's own document that a second
platform could not read, and the width of a lookalike is a percentage on
one platform and an enum on the other. Shape on this side, table on the
far one.

No Django, no clock, no configuration.
"""

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
