"""Free a bill an abandoned card screen is still holding."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.services.journal import record
from app.modules.billing.exceptions import ReasonRequired
from app.modules.billing.models import PaymentTransaction
from app.modules.billing.services import abandon_hold


def free_hold(
    db: Session,
    *,
    attempt: PaymentTransaction,
    actor: User,
    reason: str,
    now: datetime,
) -> PaymentTransaction:
    """The sweep's write without its twelve hours. A deleted account's receipt
    has no customer left, so its journal row is filed under the member of staff.
    """
    if not reason.strip():
        raise ReasonRequired
    released = abandon_hold(
        db,
        provider=attempt.provider,
        external_id=attempt.external_id,
        actor=actor,
        now=now,
    )
    record(
        db,
        customer=released.owner or actor,
        actor=actor,
        kind=ActionKind.HOLD_RELEASED,
        reason=reason,
        detail={
            "invoice": released.invoice.number,
            "provider": released.provider,
        },
    )
    return released
