"""Disconnecting a customer's Facebook from the card, all the way.

Done when the customer asks for it. The address is typed back, as for
deleting the account: nothing brings the rows back. What was there is counted
into the journal, so the card can still say how much went.
"""

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import FacebookEmailMismatch, NothingToForget
from app.modules.backoffice.services.journal import record
from app.modules.integrations.services.forget import Forgotten, forget_meta


def forget_facebook(
    db: Session, *, customer: User, actor: User, typed_email: str, reason: str
) -> Forgotten:
    if typed_email.strip().lower() != customer.email.lower():
        raise FacebookEmailMismatch
    done = forget_meta(db, owner=customer, actor=actor)
    if not done.holdings.anything:
        raise NothingToForget
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.FACEBOOK_FORGOTTEN,
        reason=reason,
        detail={
            **done.holdings.as_detail(),
            "rows": done.rows,
            "files": done.files,
            "kept_business": done.kept_business,
        },
    )
    return done


__all__ = ["forget_facebook"]
