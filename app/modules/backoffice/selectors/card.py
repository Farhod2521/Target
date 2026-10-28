"""Everything one account has, gathered for its card.

No cause: an error code, a payload, a prompt version belong to the other
console. Each figure comes from the selector the product gates on, so the
office quotes the number that actually refused somebody.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors import (
    adsets_delivering,
    ceiling_scope,
    live_groups_by_page,
    page_scope,
    trial_campaigns_left,
)
from app.modules.agent.models import AgentPolicy
from app.modules.agent.selectors import policy_for
from app.modules.backoffice.selectors.days import days_left
from app.modules.billing.constants import InvoiceStatus, PlanMove
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.billing.selectors import (
    AiBudget,
    ChatAllowance,
    Offer,
    ai_budget,
    chat_allowance,
    checkout_offers,
    every_plan,
    invoice_history,
    latest_subscription,
    live_subscription,
    orphaned_receipts,
    subscription_history,
)
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import businesses_for
from app.modules.crm.selectors import seat_capacity, team_size
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PageInstagram,
    PixelAccount,
    ProviderConnection,
)
from app.modules.integrations.selectors import (
    Pair,
    ad_accounts,
    extra_instagram_count,
    meta_connection,
    page_pairs,
    page_slots,
    pixels,
)
from app.modules.integrations.selectors.connection import pages
from app.modules.integrations.selectors.slots import Slots
from app.modules.notifications.models import TelegramChat
from app.modules.notifications.selectors import chat_for
from app.modules.referrals.constants import ReferralMode
from app.modules.referrals.models import ReferralAccess, WithdrawalRequest
from app.modules.referrals.selectors import (
    WalletBalance,
    access_of,
    invited_users,
    inviter_of,
    may_withdraw,
    payout_history,
    wallet_balance,
)
from app.modules.referrals.selectors.eligibility import may_invite

RECENT_INVOICES = 6
RECENT_CHANGES = 10
RECENT_PAYOUTS = 6


def person(db: Session, *, customer_id: uuid.UUID) -> User | None:
    """The account behind an id, if it is a customer's: never staff, never a
    CRM manager's own login."""
    return db.scalar(
        select(User).where(
            User.id == customer_id,
            User.is_staff.is_(False),
            User.crm_owner_id.is_(None),
        )
    )


@dataclass(frozen=True, slots=True)
class InstagramRow:
    name: str
    is_own: bool
    in_subscription: bool
    is_linked: bool


def instagram_rows(
    page: PageAccount, joined: list[PageInstagram]
) -> tuple[InstagramRow, ...]:
    """The page's own account first, read off the page, then every further one."""
    own = next(
        (r for r in joined if r.instagram_user_id == page.instagram_user_id), None
    )
    rows: list[InstagramRow] = []
    if page.instagram_user_id:
        username = page.instagram_username or (own.username if own else "")
        rows.append(
            InstagramRow(
                name=f"@{username}" if username else page.instagram_user_id,
                is_own=True,
                in_subscription=page.is_active,
                is_linked=own.is_linked if own else True,
            )
        )
    rows.extend(
        InstagramRow(
            name=str(r),
            is_own=False,
            in_subscription=r.is_active,
            is_linked=r.is_linked,
        )
        for r in joined
        if r.instagram_user_id != page.instagram_user_id
    )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class PageRow:
    page: PageAccount
    live_groups: int
    pairs: tuple[Pair, ...]
    instagrams: tuple[InstagramRow, ...]


def _page_rows(db: Session, *, owner: User) -> list[PageRow]:
    live = live_groups_by_page(db, owner=owner)
    listed = pages(db, owner=owner)
    joined: dict[uuid.UUID, list[PageInstagram]] = {}
    for row in db.scalars(
        select(PageInstagram)
        .where(PageInstagram.owner_id == owner.id)
        .order_by(PageInstagram.username)
    ):
        joined.setdefault(row.page_id, []).append(row)
    paired: dict[uuid.UUID, list[Pair]] = {}
    for pair in page_pairs(db, owner=owner, pages=[p for p in listed if p.is_active]):
        paired.setdefault(pair.page.id, []).append(pair)
    return [
        PageRow(
            page=page,
            live_groups=live.get(page.external_id, 0),
            pairs=tuple(paired.get(page.id, ())),
            instagrams=instagram_rows(page, joined.get(page.id, [])),
        )
        for page in listed
    ]


@dataclass(frozen=True, slots=True)
class Running:
    about: str
    used: int


@dataclass(frozen=True, slots=True)
class Limits:
    """What this account can run out of, as one question on a call."""

    pages: Slots
    extra_instagrams: int
    crm_seats: Slots
    running: tuple[Running, ...]
    ai: AiBudget
    chat: ChatAllowance
    trial_left: int | None
    has_plan: bool


def limits(db: Session, *, owner: User, now: datetime) -> Limits:
    whole = page_scope(db, owner=owner)
    sole = len(whole.pages) <= 1
    return Limits(
        pages=page_slots(db, owner=owner),
        extra_instagrams=extra_instagram_count(db, owner=owner),
        crm_seats=Slots(
            allowed=seat_capacity(db, owner=owner, at=now),
            used=team_size(db, owner=owner),
        ),
        running=tuple(
            Running(
                about="" if sole else (name or page_id),
                used=adsets_delivering(
                    db, owner=owner, scope=ceiling_scope(whole=whole, page_id=page_id)
                ),
            )
            for page_id, name in whole.pages.items()
        ),
        ai=ai_budget(db, owner=owner, now=now),
        chat=chat_allowance(db, owner=owner, now=now),
        trial_left=trial_campaigns_left(db, owner=owner),
        has_plan=live_subscription(db, owner=owner) is not None,
    )


@dataclass(frozen=True, slots=True)
class PlanChoice:
    plan: Plan
    offer: Offer

    @property
    def waits(self) -> bool:
        return self.offer.switch.move == PlanMove.WAIT


@dataclass(frozen=True, slots=True)
class PlanPicker:
    """Every tier the office may hand out, withdrawn ones too, each with what
    the customer would owe at checkout - less the unused days of the plan
    they leave. Hamyon and codes are theirs to spend, so left out."""

    choices: tuple[PlanChoice, ...]
    credit_minor: int
    credit_days: int
    currency: str


def plan_picker(db: Session, *, owner: User, now: datetime) -> PlanPicker:
    plans = every_plan(db)
    offers = checkout_offers(
        db, owner=owner, plans=plans, discounts={}, wallets={}, now=now
    )
    choices = tuple(PlanChoice(plan=plan, offer=offers[plan.code]) for plan in plans)
    restart = next((c.offer for c in choices if c.offer.switch.credit_minor), None)
    return PlanPicker(
        choices=choices,
        credit_minor=restart.switch.credit_minor if restart is not None else 0,
        credit_days=restart.switch.credit_days if restart is not None else 0,
        currency=restart.plan.currency if restart is not None else "",
    )


@dataclass(frozen=True, slots=True)
class CustomerCard:
    user: User
    businesses: list[Business]
    subscription: Subscription | None
    lapsed: Subscription | None
    days_left: int | None
    connection: ProviderConnection | None
    ad_accounts: list[AdAccount]
    page_rows: list[PageRow]
    pixels: list[PixelAccount]
    telegram: TelegramChat | None
    policy: AgentPolicy | None
    invoices: list[Invoice]
    history: list[dict[str, object]]
    paid: tuple[tuple[str, int], ...]
    old_receipts: list[Invoice]
    wallet: tuple[WalletBalance, ...]
    recent_payouts: list[WithdrawalRequest]
    referral_open: bool
    wallet_payable: bool
    referral_mode: str
    referral_access: ReferralAccess | None
    inviter: User | None
    invited: int


def _paid(db: Session, *, owner: User) -> tuple[tuple[str, int], ...]:
    """Everything paid, per currency billed in; a refunded bill went back."""
    rows = db.execute(
        select(Invoice.currency, func.sum(Invoice.amount_minor))
        .where(Invoice.owner_id == owner.id, Invoice.status == InvoiceStatus.PAID)
        .group_by(Invoice.currency)
        .order_by(Invoice.currency)
    )
    return tuple((currency, int(total)) for currency, total in rows if total)


def customer_card(db: Session, *, owner: User, now: datetime) -> CustomerCard:
    subscription = live_subscription(db, owner=owner)
    access = access_of(db, owner=owner)
    return CustomerCard(
        user=owner,
        businesses=businesses_for(db, owner=owner),
        subscription=subscription,
        lapsed=latest_subscription(db, owner=owner) if subscription is None else None,
        days_left=(
            days_left(expires_at=subscription.expires_at, now=now)
            if subscription is not None
            else None
        ),
        connection=meta_connection(db, owner=owner),
        ad_accounts=ad_accounts(db, owner=owner),
        page_rows=_page_rows(db, owner=owner),
        pixels=pixels(db, owner=owner),
        telegram=chat_for(db, owner=owner),
        policy=policy_for(db, owner=owner),
        invoices=invoice_history(db, owner=owner)[:RECENT_INVOICES],
        history=subscription_history(db, owner=owner)[:RECENT_CHANGES],
        paid=_paid(db, owner=owner),
        old_receipts=orphaned_receipts(db, email=owner.email),
        wallet=wallet_balance(db, owner=owner),
        recent_payouts=payout_history(db, owner=owner)[:RECENT_PAYOUTS],
        referral_open=may_invite(db, owner_id=owner.id),
        wallet_payable=may_withdraw(db, owner=owner),
        referral_mode=access.mode if access is not None else str(ReferralMode.AUTO),
        referral_access=access,
        inviter=inviter_of(db, owner=owner),
        invited=len(invited_users(db, owner=owner)),
    )
