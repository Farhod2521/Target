"""The office's customer list and one customer's card, as JSON.

Support, Finance and Owner only; anybody else is answered 404.
"""

import uuid
from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Db
from app.common.timezone import localtime
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ADMIN_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import amounts, choices, person_out, trace_out
from app.modules.backoffice.schemas import CustomerCardOut, CustomersOut
from app.modules.backoffice.selectors import traces
from app.modules.backoffice.selectors.card import (
    Limits,
    PageRow,
    PlanPicker,
    customer_card,
    limits,
    person,
    plan_picker,
)
from app.modules.backoffice.selectors.customers import (
    NO_MANAGER,
    SORTS,
    STATES,
    CustomerRow,
    Narrowing,
    customer_page,
)
from app.modules.backoffice.selectors.problems import Problem, problems_of
from app.modules.backoffice.services import seen
from app.modules.billing.constants import (
    HISTORY_KIND_LABELS,
    INVOICE_KIND_LABELS,
    INVOICE_STATUS_LABELS,
    SUBSCRIPTION_STATUS_LABELS,
    SubscriptionStatus,
)
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors import every_plan
from app.modules.integrations.constants import CONNECTION_STATUS_LABELS
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.referrals.constants import PAYOUT_STATUS_LABELS, REFERRAL_MODE_LABELS
from app.modules.referrals.models import WithdrawalRequest
from app.modules.sales.routers import card_out, hold_out, line_out
from app.modules.sales.selectors.board import managers
from app.modules.sales.selectors.holds import SalesRecord, sales_record

router = APIRouter(prefix="/customers")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
RECENT_SALES_LINES = 10

TERM_LABELS = {
    "trial": "Sinovda",
    "active": "Faol",
    "lapsed": "Obunasi tugagan",
    "never": "Obuna olmagan",
}


def trouble_out(problem: Problem | None) -> dict[str, Any] | None:
    if problem is None:
        return None
    return {
        "kind": problem.kind,
        "label": problem.label,
        "what": problem.what,
        "urgent": problem.urgent,
        "since": problem.since,
    }


def _term(row: CustomerRow) -> dict[str, Any]:
    live = row.subscription
    shown = live or row.ended
    if live is not None:
        state = "trial" if live.status == SubscriptionStatus.TRIAL else "active"
    else:
        state = "lapsed" if row.ended is not None else "never"
    return {
        "state": state,
        "label": TERM_LABELS[state],
        "plan": {"code": shown.plan.code, "name": shown.plan.name} if shown else None,
        "days_left": row.days_left,
        "expires_at": live.expires_at if live else None,
        "ended_on": row.ended_on,
    }


def row_out(row: CustomerRow) -> dict[str, Any]:
    user = row.user
    business = row.business
    return {
        "customer": {**(person_out(user) or {}), "phone": user.phone},
        "is_blocked": not user.is_active,
        "joined_at": user.date_joined,
        "last_login_at": user.last_login,
        "business": (
            {
                "name": business.name,
                "direction": business.direction.label_uz if business.direction else "",
            }
            if business is not None
            else None
        ),
        "term": _term(row),
        "trouble": trouble_out(row.trouble),
        "pages": (
            {"used": row.pages.used, "allowed": row.pages.allowed}
            if row.pages
            else None
        ),
        "running": row.running,
        "spend": amounts(row.spend),
        "leads": row.leads,
        "paid_total": amounts(row.paid_total),
        "paid_before": row.paid_before,
        "sales_manager": person_out(row.manager),
    }


@router.get("", responses={200: {"model": CustomersOut}})
def customers(
    db: Db,
    user: Admin,
    q: str = Query(
        "", description="E-mail, name, phone, invoice number, ad account or page id."
    ),
    state: str = Query("", description="A chip from `states`."),
    plan: str = Query("", description="A plan code: the live plan, else the last one."),
    joined_from: date | None = Query(
        None, description="Office calendar day, included."
    ),
    joined_to: date | None = Query(None, description="Office calendar day, included."),
    manager: str = Query("", description="A sales manager's id, or `none`."),
    sort: str = Query("", description="A value from `sorts`; empty follows the chip."),
    offset: int = Query(0, ge=0),
    as_of: datetime | None = Query(None, description="`as_of` from the first page."),
) -> dict[str, Any]:
    now = localtime()
    page = customer_page(
        db,
        now=now,
        narrowing=Narrowing(
            term=q.strip(),
            state=state if state in dict(STATES) else "",
            plan=plan,
            joined_from=joined_from,
            joined_to=joined_to,
            manager=manager,
            sort=sort if sort in dict(SORTS) else "",
        ),
        offset=offset,
        as_of=as_of,
    )
    return {
        "rows": [row_out(row) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "as_of": page.as_of,
        "states": choices(STATES),
        "sorts": choices(SORTS),
        "plans": choices([(p.code, p.name) for p in every_plan(db)]),
        "managers": choices(
            [(NO_MANAGER, "Menejersiz")]
            + [(str(m.id), m.full_name or m.email) for m in managers(db)]
        ),
    }


# -- one customer's card -------------------------------------------------------------


def _label(labels: Mapping[Any, Any], value: str) -> str:
    return str(labels.get(value, value))


def _plan_line(plan: Plan | None) -> dict[str, Any] | None:
    return {"code": plan.code, "name": plan.name} if plan is not None else None


def _subscription_out(
    row: Subscription | None, *, days: int | None
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "plan": _plan_line(row.plan),
        "status": row.status,
        "status_label": _label(SUBSCRIPTION_STATUS_LABELS, row.status),
        "started_at": row.started_at,
        "expires_at": row.expires_at,
        "ended_at": row.ended_at,
        "days_left": days,
        "extra_pages": row.extra_pages,
        "setup_completed_at": row.setup_completed_at,
        "activated_by": person_out(row.activated_by),
        "note": row.note,
    }


def _connection_out(link: ProviderConnection | None) -> dict[str, Any] | None:
    if link is None:
        return None
    return {
        "status": link.status,
        "status_label": _label(CONNECTION_STATUS_LABELS, link.status),
        "name": link.external_user_name,
        "expires_at": link.expires_at,
        "last_verified_at": link.last_verified_at,
        "last_error_code": link.last_error_code,
        "action_required": link.action_required_at is not None,
        "connected_at": link.created_at,
    }


def _ad_account_out(account: AdAccount) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "external_id": account.external_id,
        "name": account.name,
        "currency": account.currency,
        "is_active": account.is_active,
        "may_advertise": account.may_advertise,
        "payment_due": account.payment_due,
        "balance_minor": account.balance_minor,
        "synced_at": account.synced_at,
    }


def _page_out(row: PageRow) -> dict[str, Any]:
    page = row.page
    return {
        "id": str(page.id),
        "external_id": page.external_id,
        "name": page.name,
        "is_active": page.is_active,
        "leadgen_subscribed": page.leadgen_subscribed,
        "may_advertise": page.may_advertise,
        "live_groups": row.live_groups,
        "pairs": [
            {
                "ad_account_id": str(pair.account.id),
                "ad_account_name": pair.account.name or pair.account.external_id,
                "stored": pair.stored,
            }
            for pair in row.pairs
        ],
        "instagrams": [
            {
                "name": insta.name,
                "is_own": insta.is_own,
                "in_subscription": insta.in_subscription,
                "is_linked": insta.is_linked,
            }
            for insta in row.instagrams
        ],
    }


def _invoice_out(invoice: Invoice) -> dict[str, Any]:
    return {
        "number": invoice.number,
        "kind": invoice.kind,
        "kind_label": _label(INVOICE_KIND_LABELS, invoice.kind),
        "status": invoice.status,
        "status_label": _label(INVOICE_STATUS_LABELS, invoice.status),
        "plan": _plan_line(invoice.plan),
        "amount_minor": invoice.amount_minor,
        "wallet_minor": invoice.wallet_minor,
        "credit_minor": invoice.credit_minor,
        "currency": invoice.currency,
        "period_days": invoice.period_days,
        "pages": invoice.pages,
        "seats": invoice.seats,
        "manual_method": invoice.manual_method,
        "recorded_by": person_out(invoice.recorded_by),
        "created_at": invoice.created_at,
        "paid_at": invoice.paid_at,
    }


def _history_out(row: dict[str, Any]) -> dict[str, Any]:
    change = row["change"]
    return {
        "kind": change.kind,
        "kind_label": _label(HISTORY_KIND_LABELS, change.kind),
        "from_plan": _plan_line(change.from_plan),
        "to_plan": _plan_line(change.to_plan),
        "days": change.days,
        "expires_before": change.expires_before,
        "expires_after": change.expires_after,
        "invoice": change.invoice.number if change.invoice else "",
        "paid_minor": row["paid_minor"],
        "actor": person_out(change.actor),
        "reason": change.reason,
        "occurred_at": change.occurred_at,
    }


def _payout_out(ask: WithdrawalRequest) -> dict[str, Any]:
    return {
        "id": str(ask.id),
        "status": ask.status,
        "status_label": _label(PAYOUT_STATUS_LABELS, ask.status),
        "amount_minor": ask.amount_minor,
        "currency": ask.currency,
        "method": ask.method,
        "card_last4": ask.card_last4,
        "created_at": ask.created_at,
        "decided_at": ask.decided_at,
    }


def _limits_out(found: Limits) -> dict[str, Any]:
    return {
        "pages": {"used": found.pages.used, "allowed": found.pages.allowed},
        "extra_instagrams": found.extra_instagrams,
        "crm_seats": {"used": found.crm_seats.used, "allowed": found.crm_seats.allowed},
        "running": [{"about": row.about, "used": row.used} for row in found.running],
        "ai": {
            "spent_minor": found.ai.spent_minor,
            "limit_minor": found.ai.limit_minor,
            "currency": found.ai.currency,
            "entitled": found.ai.entitled,
        },
        "chat": {"used": found.chat.used, "allowed": found.chat.limit},
        "trial_left": found.trial_left,
        "has_plan": found.has_plan,
    }


def _picker_out(picker: PlanPicker) -> dict[str, Any]:
    return {
        "choices": [
            {
                "code": choice.plan.code,
                "name": choice.plan.name,
                "is_active": choice.plan.is_active,
                "currency": choice.plan.currency,
                "due_minor": choice.offer.due_minor,
                "waits": choice.waits,
            }
            for choice in picker.choices
        ],
        "credit_minor": picker.credit_minor,
        "credit_days": picker.credit_days,
        "currency": picker.currency,
    }


def _sales_out(record: SalesRecord) -> dict[str, Any]:
    return {
        "claim": card_out(record.claim) if record.claim is not None else None,
        "closed": len(record.closed),
        "lines": [line_out(line) for line in record.lines[:RECENT_SALES_LINES]],
        "hold": hold_out(record.hold),
    }


@router.get("/{customer_id}", responses={200: {"model": CustomerCardOut}})
def customer(customer_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """One account, whole. Opening it is written to the journal."""
    owner = person(db, customer_id=customer_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    seen(db, customer=owner, actor=user)
    db.commit()
    now = localtime()
    card = customer_card(db, owner=owner, now=now)
    access = card.referral_access
    return {
        "profile": {
            **(person_out(owner) or {}),
            "phone": owner.phone,
            "language": owner.language,
            "is_blocked": not owner.is_active,
            "joined_at": owner.date_joined,
            "last_login_at": owner.last_login,
            "prepared_at": owner.prepared_at,
        },
        "businesses": [
            {
                "id": str(business.id),
                "name": business.name,
                "direction": business.direction.label_uz if business.direction else "",
                "page_id": str(business.page_id) if business.page_id else None,
                "city": business.city,
                "country_code": business.country_code,
                "contact_phone": business.contact_phone,
                "website": business.website,
            }
            for business in card.businesses
        ],
        "subscription": _subscription_out(card.subscription, days=card.days_left),
        "lapsed": _subscription_out(card.lapsed, days=None),
        "limits": _limits_out(limits(db, owner=owner, now=now)),
        "plan_picker": _picker_out(plan_picker(db, owner=owner, now=now)),
        "meta": _connection_out(card.connection),
        "ad_accounts": [_ad_account_out(account) for account in card.ad_accounts],
        "pages": [_page_out(row) for row in card.page_rows],
        "pixels": [
            {
                "external_id": pixel.external_id,
                "name": pixel.name,
                "is_active": pixel.is_active,
            }
            for pixel in card.pixels
        ],
        "telegram": (
            {
                "username": card.telegram.username,
                "is_active": card.telegram.is_active,
                "linked_at": card.telegram.linked_at,
                "last_error_at": card.telegram.last_error_at,
            }
            if card.telegram is not None
            else None
        ),
        "agent": (
            {
                "is_enabled": card.policy.is_enabled,
                "last_run_at": card.policy.last_run_at,
            }
            if card.policy is not None
            else None
        ),
        "money": {
            "paid": amounts(card.paid),
            "invoices": [_invoice_out(invoice) for invoice in card.invoices],
            "history": [_history_out(row) for row in card.history],
            "old_receipts": [_invoice_out(invoice) for invoice in card.old_receipts],
        },
        "referral": {
            "mode": card.referral_mode,
            "mode_label": _label(REFERRAL_MODE_LABELS, card.referral_mode),
            "mode_reason": access.reason if access is not None else "",
            "mode_set_by": person_out(access.set_by) if access is not None else None,
            "open": card.referral_open,
            "wallet_payable": card.wallet_payable,
            "inviter": person_out(card.inviter),
            "invited": card.invited,
            "wallet": [
                {
                    "currency": row.currency,
                    "earned_minor": row.earned_minor,
                    "paid_minor": row.paid_minor,
                    "spent_minor": row.spent_minor,
                    "held_minor": row.held_minor,
                    "available_minor": row.available_minor,
                }
                for row in card.wallet
            ],
            "payouts": [_payout_out(ask) for ask in card.recent_payouts],
        },
        "sales": _sales_out(sales_record(db, client_id=owner.id, now=now)),
        "problems": [
            trouble_out(problem)
            for problem in problems_of(db, owner_id=owner.id, now=now)
        ],
        "traces": [trace_out(row) for row in traces(db, owner=owner)],
    }
