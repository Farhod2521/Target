"""Whether an ad account may deliver at all, as its last read said.

A network goes on calling a campaign ACTIVE on an account it has switched
off: the switch is the campaign's, the stop is the account's. A screen that
reads only the campaign says «Ishlayapti» over advertising nobody is shown.
"""

from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, or_

from app.modules.integrations.models import AdAccount

StoppedKind = Literal["payment", "closed", "disabled"]

_PAYMENT: Final = frozenset({"payment_failed", "disabled_payment"})
_CLOSED: Final = frozenset({"closed"})
STOPPED_STANDINGS: Final = _PAYMENT | _CLOSED | frozenset({"disabled"})
# Meta's ``account_status`` for closing and closed, kept for an account read
# at connect only: that read stores the number and no standing.
_CLOSED_STATUSES: Final = frozenset({"100", "101"})


def stopped_kind(account: Any) -> StoppedKind | None:
    """Why this account delivers nothing, or nothing when it may deliver.

    ``may_advertise`` of ``None`` is an account nobody asked about: it is
    not called stopped.
    """
    if account is None:
        return None
    standing = str(getattr(account, "standing", "") or "")
    if account.may_advertise is not False and standing not in STOPPED_STANDINGS:
        return None
    if account.payment_due or standing in _PAYMENT:
        return "payment"
    if standing in _CLOSED or str(account.account_status or "") in _CLOSED_STATUSES:
        return "closed"
    return "disabled"


def stopped_clause() -> ColumnElement[bool]:
    """``AdAccount`` rows :func:`stopped_kind` answers for, as SQL."""
    return or_(
        AdAccount.may_advertise.is_(False),
        AdAccount.standing.in_(sorted(STOPPED_STANDINGS)),
    )


__all__ = ["STOPPED_STANDINGS", "StoppedKind", "stopped_clause", "stopped_kind"]
