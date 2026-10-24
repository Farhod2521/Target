"""What a campaign or an ad group is doing, as its adverts show it."""

from collections.abc import Collection

from adskit.refs import Delivery

ACTIVE: Delivery = "active"
PENDING: Delivery = "pending"
REJECTED: Delivery = "rejected"
PAUSED: Delivery = "paused"
OFF: frozenset[Delivery] = frozenset({"paused", "paused_above"})


def shown_delivery(*, own: Delivery, ads: Collection[Delivery]) -> Delivery:
    """The state to draw for an object, given its adverts' states."""
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
