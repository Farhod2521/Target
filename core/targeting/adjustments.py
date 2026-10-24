"""A field this package changed on its own, and why.

Its own module rather than a corner of :mod:`core.targeting.contracts`, and
the move is structural rather than tidiness. Every part of this package
produces these - the validator, the mode, the audience choice - and the
contracts module has to be free to import the values *they* define. One
module that depends on nothing is what keeps that from being a cycle.

No Django, no clock, no configuration.
"""

from dataclasses import dataclass
from typing import Literal

# Why a field was changed. A code rather than a sentence, for the same
# reason the exceptions carry numbers: three languages read these.
AdjustmentReason = Literal[
    "special_ad_category",
    "unconfirmed_interest",
    "unsupported_placement",
    "age_out_of_range",
    "radius_out_of_range",
    "location_missing",
    "conversion_source_missing",
    # The audience mode removed or narrowed a field the provider will not
    # accept beside it. One reason for several fields, exactly as
    # ``special_ad_category`` is: what a person needs told is which
    # decision caused it, and the field name says the rest.
    "automatic_targeting",
    # An audience that was both shown to and kept from the same people.
    # The exclusion is the half that survives - see
    # :mod:`core.targeting.audiences`.
    "audience_on_both_sides",
    # A chosen audience that is no longer usable, or no longer there. Not
    # an error: the campaign is built without it and the sentence names
    # which one went, because a list that silently shrinks between one
    # screen and the next is how trust in the whole flow goes.
    "audience_unavailable",
    # A "most per result" figure attached to a goal that has no result to
    # put a price on - an ad bought to be seen, a visit counted on the
    # advertiser's own side. Dropped rather than refused, because the
    # answer was given on a screen two steps before the goal could have
    # been changed since.
    "goal_takes_no_cap",
    # A total spend ceiling below one day's budget. See
    # :func:`core.targeting.budget.spend_limits_fit`.
    "cap_below_daily",
]


@dataclass(frozen=True, slots=True)
class Adjustment:
    """A field this package changed on its own, and why.

    Not an error: the spec is valid and the campaign will run. It is
    something the owner has to be told, because they typed 12 and the
    provider will be sent 24, and a number that changes with no sentence
    beside it reads as a bug.
    """

    field: str
    reason: AdjustmentReason
    detail: str = ""


__all__ = ["Adjustment", "AdjustmentReason"]
