"""The waiting list's lines about things only Meta's own screens can fix."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.block_causes import block_cause
from app.modules.integrations.models import AdAccount
from app.modules.integrations.selectors.watch import meta_action_required
from core.inbox import InboxItem


def meta_items(
    db: Session, *, owner: User, accounts: Sequence[AdAccount]
) -> list[InboxItem]:
    """Meta holding the person, and accounts that cannot advertise. Usually neither."""
    return [
        *_hold(db, owner=owner),
        *(item for account in accounts for item in _blocked(account=account)),
    ]


def _hold(db: Session, *, owner: User) -> list[InboxItem]:
    hold = meta_action_required(db, owner=owner)
    if hold is None:
        return []
    return [
        InboxItem(
            key="meta_hold",
            kind="meta_hold",
            level="urgent",
            title="Meta shaxsingizni tasdiqlashni so'rayapti",
            body=(
                "Tasdiqlamaguningizcha Meta reklamadagi hech bir o'zgarishni "
                "qabul qilmaydi."
            ),
            action="Meta'da tasdiqlash",
            href=hold.manager_url,
        )
    ]


def _blocked(*, account: AdAccount) -> list[InboxItem]:
    # ``None`` is an account Meta was never asked about: carry on.
    if account.may_advertise is not False:
        return []
    if account.payment_due or account.standing == "disabled_payment":
        # Money: the stop line says it, with its reason.
        return []
    cause = block_cause(account)
    if cause is None:
        return []
    return [
        InboxItem(
            key=f"account_blocked:{account.external_id}:{account.account_status}",
            kind="account_blocked",
            level="urgent",
            title=cause.title,
            body=cause.body,
            action=cause.action if cause.href else "",
            href=cause.href,
        )
    ]


__all__ = ["meta_items"]
