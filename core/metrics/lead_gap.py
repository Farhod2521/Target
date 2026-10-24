"""Whether the provider counted leads that never reached this product.

There are always two counts. The provider counts a form submission at its
end; this product counts the ones that arrived in its own table. They differ
for ordinary reasons - a lead either side of midnight, a webhook that landed
a minute late - and they differ for the one reason that matters: leads that
were paid for and never arrived.

Only the provider's surplus is a gap. Ours being higher means the same form
collected outside the advertising, which is nobody's fault.

**Two bars, because two different things are decided on it.** A figure on
a screen stops being trustworthy at a small gap - a cost per lead a tenth
too dear is a wrong figure - so the screen bar is low. Interrupting somebody
with "your leads are going missing" needs a gap that could not be a
Tuesday's rounding, so the alarm bar is higher and wants a count as well as
a share: two of three missing is a share that means nothing.

Only meaningful for groups whose form lives on the advert. A group sending
people to a website form is counted by the provider through a pixel, and
those leads never come to this product at all - comparing them would call
every website campaign broken.
"""

from typing import Final

# When a figure built on our count stops being shown.
SCREEN_GAP_PCT: Final = 10
SCREEN_GAP_MISSING: Final = 2

# When somebody is told.
ALARM_GAP_PCT: Final = 20
ALARM_GAP_MISSING: Final = 3


def missing_leads(*, reported: int, ours: int, share_pct: int, at_least: int) -> int:
    """How many of the provider's leads are not here, when that is a gap.

    Nought when the gap is below either bar - the count or the share of the
    provider's own total - and nought when ours is the larger count.
    """
    missing = reported - ours
    if missing < at_least or missing * 100 < share_pct * reported:
        return 0
    return missing


__all__ = [
    "ALARM_GAP_MISSING",
    "ALARM_GAP_PCT",
    "SCREEN_GAP_MISSING",
    "SCREEN_GAP_PCT",
    "missing_leads",
]
