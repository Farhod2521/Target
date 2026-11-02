"""Taking a customer's whole CRM away from their card."""

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import CrmEmailMismatch
from app.modules.backoffice.selectors.crm import CrmTotals, crm_totals
from app.modules.backoffice.services.journal import record
from app.modules.crm.services import erase_crm


def erase_customer_crm(
    db: Session, *, customer: User, actor: User, typed_email: str, reason: str
) -> CrmTotals:
    """The address has to be typed back, as for deleting the account: nothing
    brings these rows back. The journal keeps how much went."""
    if typed_email.strip().lower() != customer.email.lower():
        raise CrmEmailMismatch
    totals = crm_totals(db, owner=customer)
    erase_crm(db, owner=customer, actor=actor)
    record(
        db,
        customer=customer,
        actor=actor,
        kind=ActionKind.CRM_ERASED,
        reason=reason,
        detail=totals.as_detail(),
    )
    return totals
