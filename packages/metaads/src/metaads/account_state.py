"""Whether one ad account can pay for its advertising, read on every sync.

The connect handshake reads an account once. A card that stops being
charged does so weeks later, and Meta's only signal is on the account: the
campaigns go on saying ACTIVE while nothing is delivered.

Two reads at most. The payment method and the prepay flag need a role on
the account that some tokens do not carry, and Meta refuses the whole read
rather than leaving those fields out - so a refusal is retried without them
and the money half still arrives.
"""

import logging
from typing import Any, Final

from adskit.dto import AccountStateDTO
from adskit.refs import AccountStanding, ExternalRef, MinorUnits

from metaads.client import GraphClient
from metaads.dto_base import _minor_units
from metaads.errors import MetaAPIError

logger = logging.getLogger(__name__)

BASE_FIELDS: Final = "account_status,disable_reason,spend_cap,amount_spent,balance"
# Readable only with ADVERTISE or MANAGE on the account.
FUNDING_FIELDS: Final = "is_prepay_account"

# ``account_status``, as published: 1 active, 2 disabled, 3 unsettled,
# 7 pending risk review, 8 pending settlement, 9 in grace period,
# 100 pending closure, 101 closed.
_STANDING: Final[dict[int, AccountStanding]] = {
    1: "active",
    2: "disabled",
    3: "payment_failed",
    7: "review",
    8: "payment_pending",
    9: "payment_grace",
    100: "closed",
    101: "closed",
}

# ``disable_reason`` 3 is RISK_PAYMENT: switched off over a payment.
_PAYMENT_RISK: Final = 3


def standing_of(*, status: int, reason: int) -> AccountStanding:
    """The account's two numbers, as one word the domain can act on."""
    standing = _STANDING.get(status, "unknown")
    if standing == "disabled" and reason == _PAYMENT_RISK:
        return "disabled_payment"
    return standing


def read_account_state(
    *, account: ExternalRef, token: str, client: GraphClient
) -> AccountStateDTO:
    """One account's money, translated. Raises ``MetaError`` like any read."""
    path = account.id if account.id.startswith("act_") else f"act_{account.id}"
    try:
        payload = client.get(path, fields=f"{BASE_FIELDS},{FUNDING_FIELDS}")
    except MetaAPIError as exc:
        logger.info("prepay flag unreadable on %s, read without it: %s", path, exc)
        payload = client.get(path, fields=BASE_FIELDS)
    return _state(account=account, payload=payload)


def _state(*, account: ExternalRef, payload: dict[str, Any]) -> AccountStateDTO:
    status = _int(payload.get("account_status"))
    reason = _int(payload.get("disable_reason"))
    prepaid = payload.get("is_prepay_account")
    return AccountStateDTO(
        ref=account,
        standing=standing_of(status=status, reason=reason),
        raw_status=str(status or ""),
        raw_reason=str(reason or ""),
        spend_cap_minor=_minor(payload.get("spend_cap")),
        amount_spent_minor=_minor(payload.get("amount_spent")),
        balance_minor=_minor(payload.get("balance")),
        prepaid=prepaid if isinstance(prepaid, bool) else None,
    )


def _int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _minor(value: object) -> MinorUnits:
    """Money arrives quoted on some edges and bare on others; nought if absent."""
    if value is None or isinstance(value, bool):
        return MinorUnits(0)
    return MinorUnits(_minor_units(str(value)) or 0)


__all__ = ["read_account_state", "standing_of"]
