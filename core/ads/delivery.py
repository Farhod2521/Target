"""What a campaign or an ad group is doing, as its adverts show it.

A provider says "under review" only about an advert. Meta's campaign and ad
set statuses have no such word: while every advert inside is still being
reviewed or prepared, the campaign and its group read ``ACTIVE`` - and a
badge drawn from that says "running" about something nobody has seen yet.
Ads Manager answers from the adverts instead, and so does this.

Only an object whose own state is "active" is rolled up. Every other state
is already the more useful thing to say: a paused group is paused whatever
its adverts are doing.

The same goes the other way. Switching off every advert, or every group,
in Ads Manager leaves the campaign itself ``ACTIVE``, and a badge drawn
from that says "running" about something that cannot spend.

For the screen only. The stored state stays the provider's, because the
rules that read it - what counts against a plan, what the agent may touch -
are about the object's own switch, not about its adverts.
"""

from collections.abc import Collection

from adskit.refs import Delivery

ACTIVE: Delivery = "active"
PENDING: Delivery = "pending"
REJECTED: Delivery = "rejected"
PAUSED: Delivery = "paused"
# An advert's states that spend nothing: its own switch off, or a parent's.
OFF: frozenset[Delivery] = frozenset({"paused", "paused_above"})


def shown_delivery(*, own: Delivery, ads: Collection[Delivery]) -> Delivery:
    """The state to draw for an object, given its adverts' states.

    Running while any advert runs. Otherwise under review while any advert
    is, refused when every advert was, and paused when the rest are off.
    No adverts known yet keeps the object's own state.
    """
    if own != ACTIVE or not ads or ACTIVE in ads:
        return own
    if PENDING in ads:
        return PENDING
    if all(state == REJECTED for state in ads):
        return REJECTED
    if any(state in OFF for state in ads):
        return PAUSED
    return own


__all__ = ["shown_delivery"]
