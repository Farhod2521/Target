"""The client behind a card, in short and to read only: what a Sales or
renewal manager needs before the call. The whole office card (money back,
days, pages, blocks) stays with Support, Finance and the Owner."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.selectors.card import customer_card
from app.modules.billing.constants import (
    INVOICE_KIND_LABELS,
    INVOICE_STATUS_LABELS,
    SUBSCRIPTION_STATUS_LABELS,
)
from app.modules.integrations.constants import CONNECTION_STATUS_LABELS

RECENT_BILLS = 10


def _label(labels: Any, value: str) -> str:
    return str(labels.get(value, value))


def brief(db: Session, *, owner: User, now: datetime) -> dict[str, Any]:
    card = customer_card(db, owner=owner, now=now)
    term = card.subscription or card.lapsed
    link = card.connection
    return {
        "profile": {
            "id": str(owner.id),
            "name": owner.full_name or owner.email,
            "email": owner.email,
            "phone": owner.phone,
            "language": owner.language,
            "is_blocked": not owner.is_active,
            "joined_at": owner.date_joined,
            "last_login_at": owner.last_login,
        },
        "businesses": [
            {
                "name": business.name,
                "direction": business.direction.label_uz if business.direction else "",
                "city": business.city,
            }
            for business in card.businesses
        ],
        "subscription": {
            "plan": term.plan.name if term.plan is not None else "",
            "status": term.status,
            "status_label": _label(SUBSCRIPTION_STATUS_LABELS, term.status),
            "started_at": term.started_at,
            "expires_at": term.expires_at,
            "days_left": card.days_left if term is card.subscription else None,
        }
        if term is not None
        else None,
        "meta": {
            "status": link.status,
            "status_label": _label(CONNECTION_STATUS_LABELS, link.status),
            "name": link.external_user_name,
            "action_required": link.action_required_at is not None,
        }
        if link is not None
        else None,
        "pages": [
            {
                "name": row.page.name,
                "is_active": row.page.is_active,
                "live_groups": row.live_groups,
                "instagrams": [insta.name for insta in row.instagrams],
            }
            for row in card.page_rows
        ],
        "telegram": card.telegram is not None and card.telegram.is_active,
        "bills": [
            {
                "number": invoice.number,
                "kind_label": _label(INVOICE_KIND_LABELS, invoice.kind),
                "status": invoice.status,
                "status_label": _label(INVOICE_STATUS_LABELS, invoice.status),
                "plan": invoice.plan.name if invoice.plan is not None else "",
                "amount_minor": invoice.amount_minor,
                "currency": invoice.currency,
                "period_days": invoice.period_days,
                "created_at": invoice.created_at,
                "paid_at": invoice.paid_at,
            }
            for invoice in card.invoices[:RECENT_BILLS]
        ],
    }
