"""Taking a bill off the books without losing it.

An archived bill leaves the lists and the takings, and stays in the database
with who took it off and why. Nothing the customer holds moves: their days,
pages, seats, referral rewards and commissions read the bill as before, because
one bill's share of them cannot be told from the rest. A bill still open is
cancelled with it, or the customer could go on to pay something nobody can see.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.exceptions import (
    InvoiceAlreadyArchived,
    InvoiceBeingPaid,
)
from app.modules.backoffice.services.journal import record
from app.modules.billing.constants import InvoiceStatus
from app.modules.billing.exceptions import ReasonRequired
from app.modules.billing.models import Invoice


def archive_invoice(
    db: Session, *, invoice: Invoice, actor: User, reason: str, now: datetime
) -> Invoice:
    """A deleted account's receipt has no customer left, so its journal row is
    filed under the member of staff."""
    if not reason.strip():
        raise ReasonRequired
    if invoice.archived_at is not None:
        raise InvoiceAlreadyArchived
    if invoice.status == InvoiceStatus.HELD:
        raise InvoiceBeingPaid
    was = invoice.status
    if invoice.status == InvoiceStatus.PENDING:
        invoice.status = InvoiceStatus.CANCELED
        invoice.canceled_at = now
    invoice.archived_at = now
    invoice.archived_by_id = actor.id
    invoice.archive_reason = reason.strip()
    db.flush()
    record(
        db,
        customer=invoice.owner or actor,
        actor=actor,
        kind=ActionKind.INVOICE_ARCHIVED,
        reason=reason,
        detail={"invoice": invoice.number, "status": str(was)},
    )
    return invoice
