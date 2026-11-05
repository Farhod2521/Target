"""Send a paid bill's money back to the card it came from."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.services.journal import record
from app.modules.billing.exceptions import NothingToRefund, ReasonRequired
from app.modules.billing.models import Invoice
from app.modules.billing.selectors import performed_attempt
from app.modules.billing.services import return_payment


def refund_invoice(
    db: Session, *, invoice: Invoice, actor: User, reason: str, now: datetime
) -> Invoice:
    """The days the bill gave are taken back as a provider's own cancel takes
    them. A deleted account's receipt has no customer left, so its journal row
    is filed under the member of staff."""
    if not reason.strip():
        raise ReasonRequired
    attempt = performed_attempt(db, invoice=invoice)
    if attempt is None:
        raise NothingToRefund
    returned = return_payment(db, attempt=attempt, actor=actor, now=now)
    record(
        db,
        customer=invoice.owner or actor,
        actor=actor,
        kind=ActionKind.INVOICE_REFUNDED,
        reason=reason,
        detail={
            "invoice": invoice.number,
            "provider": returned.provider,
            "amount_minor": returned.amount_minor,
            "currency": returned.currency,
        },
    )
    return invoice
