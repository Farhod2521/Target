"""Response shapes for plans, checkout and bills, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.billing.selectors.pages import PageMix
from app.modules.billing.selectors.plans import TierLine
from app.modules.billing.selectors.promo import ChatAllowance


class ShownPrices(BaseModel):
    """A plan's prices as this visitor is shown them; print these."""

    currency: str = Field(description="`UZS` (so'm) or `USD` (dollars and cents).")
    price: float
    extra_page_price: float
    per_page: float | None
    approximate: bool = Field(description="Show as `≈`: the payment is in so'm.")


class PlanOut(BaseModel):
    id: str
    code: str
    name: str
    tagline: str
    price: int
    currency: str
    period_days: int
    max_adsets: int
    daily_chat_requests: int = Field(description="AI chat questions a day.")
    included_pages: int
    included_google_accounts: int
    extra_page_price: int
    is_one_time: bool
    features: list[TierLine]
    highlights: list[str]
    per_page: int | None
    shown: ShownPrices | None = Field(
        None, description="On the landing page and plan lists only."
    )


class SubscriptionOut(BaseModel):
    id: str
    status: str = Field(description="`trial`, `active`, `expired` or `canceled`.")
    plan: PlanOut
    extra_pages: int
    started_at: datetime
    expires_at: datetime
    term_started_at: datetime | None
    setup_completed_at: datetime | None = Field(
        description="Null until the owner finishes setup («Yakunlash»)."
    )
    ad_account_id: str | None


class InvoiceOut(BaseModel):
    number: str
    kind: str = Field(description="`plan`, `pages` or `seats`.")
    status: str = Field(description="`pending`, `held`, `paid`, ...")
    plan: PlanOut | None
    amount_minor: int = Field(description="What is due, in minor units.")
    credit_minor: int
    wallet_minor: int
    currency: str
    period_days: int
    pages: int
    pages_minor: int
    seats: int = Field(0, description="CRM manager seats on the bill.")
    seats_minor: int = 0
    expires_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    paid_via: str


class OfferOut(BaseModel):
    plan: PlanOut
    move: str = Field(
        description="What buying it does: `stack`, `restart` or `wait` (not now)."
    )
    until: datetime | None = Field(description="With `wait`: when it becomes possible.")
    credit_days: int
    price_minor: int
    discount_minor: int = Field(
        description="All the discount: `offer_minor` + `promo_minor`."
    )
    offer_minor: int = Field(
        0, description="The sales manager's offer (20% or 10%) on the plan price."
    )
    promo_minor: int = Field(
        0, description="The typed code, on the price left after the offer."
    )
    credit_minor: int = Field(description="Unused days of the current plan, credited.")
    wallet_minor: int
    pages: int
    pages_minor: int
    page_credit_minor: int
    seats: int = Field(description="CRM manager seats the bill renews.")
    seats_minor: int
    seat_credit_minor: int = Field(description="Unused days of the seats, credited.")
    due_minor: int
    due_without_wallet_minor: int


class PlanCard(BaseModel):
    code: str
    offer: OfferOut
    tag: str = Field(description="`running`, `last` or empty.")
    action: str = Field(description="`pick`, `renew`, `switch` or `wait`.")


class PromoQuote(BaseModel):
    code: str
    base_minor: int
    discount_minor: int
    total_minor: int
    percent: int
    currency: str


class RenewalPageLine(BaseModel):
    id: str
    external_id: str
    name: str
    dropped: bool = Field(description="Unticked: released once the bill is paid.")


class RenewalPagesOut(BaseModel):
    free: int = Field(description="Pages the plan and gifts give.")
    used: int = Field(description="Pages (and extra Instagram accounts) connected.")
    bought: int = Field(description="Page slots bought on the period that ends.")
    paid_used: int = Field(
        description="Connected pages in bought slots: how many may be unticked."
    )
    empty: int = Field(description="Bought slots no page uses.")
    drop_empty: int
    carried: int = Field(description="Slots the bill renews.")
    price_minor: int = Field(description="One slot for the plan's period.")
    lines: list[RenewalPageLine] = Field(
        description="Every connected page; empty when none sits in a bought slot."
    )


class RenewalSeatLine(BaseModel):
    member_id: str
    name: str
    email: str
    page: str
    dropped: bool = Field(description="Unticked: off the team once the bill is paid.")


class RenewalSeatsOut(BaseModel):
    bought: int = Field(description="Seats bought on the period that ends.")
    carried: int = Field(description="Seats the bill renews.")
    price_minor: int = Field(description="One seat for the plan's period.")
    lines: list[RenewalSeatLine] = Field(
        description="Managers in bought seats; the free page seats are not billed."
    )


class RenewalOut(BaseModel):
    pages: RenewalPagesOut
    seats: RenewalSeatsOut


class SalesOfferOut(BaseModel):
    percent: int = Field(description="20 for the first day, then 10.")
    ends_at: datetime = Field(description="When this percent ends.")
    pay_until: datetime = Field(description="A bill priced now is payable until then.")


class PricedChoice(BaseModel):
    cards: list[PlanCard]
    promo_typed: str
    sales_offer: SalesOfferOut | None = Field(
        None,
        description="The sales manager's offer on the first plan. The cards and "
        "`chosen` already take it off; a code is taken off what is left. Start "
        "and one-time plans are not discounted: their `offer_minor` is 0.",
    )
    promo_quote: PromoQuote | None = Field(None, description="The typed code applies.")
    promo_error: str | None = Field(None, description="Why the typed code does not.")
    chosen: OfferOut | None = Field(None, description="Only when `plan` was asked.")
    chosen_ends_at: datetime | None = None
    pages_dropped: bool | None = None
    carried_pages: int | None = None
    wallet_balance_minor: int | None = None
    renewal: RenewalOut | None = Field(
        None, description="With `plan`: the extra pages and seats `chosen` renews."
    )


class StatusOut(BaseModel):
    is_read_only: bool = Field(description="No live plan: the cabinet only reads.")
    subscription: SubscriptionOut | None
    never_subscribed: bool
    may_prepare: bool
    days_left: int | None
    ending_soon: bool = Field(description="Show the renewal reminder.")
    lapse_until: str = Field(description="When paused adverts will be deleted.")


class TermOut(BaseModel):
    days_left: int
    days_total: int
    percent_left: int


class Slots(BaseModel):
    allowed: int
    used: int
    free: int


class TrialOut(BaseModel):
    allowed: int
    used: int


class PageOfferOut(BaseModel):
    plan_code: str
    currency: str
    price_minor: int = Field(description="One extra page for a full period.")
    days: int
    until: str | None
    sellable: bool
    needs_plan: bool


class PageQuoteOut(BaseModel):
    count: int
    total_minor: int
    wallet_minor: int
    due_minor: int


class RedemptionOut(BaseModel):
    id: str
    code: str
    status: str
    granted_days: int
    granted_pages: int
    plan: PlanOut | None
    redeemed_at: datetime | None


class AnnouncementOut(BaseModel):
    redemption: RedemptionOut | None
    free_slots: int
    choices: list[dict[str, Any]] = Field(description="Pages that may be taken.")
    can_choose: bool


class Provider(BaseModel):
    name: str = Field(description="Send as `provider` to checkout.")
    label: str


class DisplayOut(BaseModel):
    """Prices stay in so'm everywhere; this only says how to show them.

    With ``currency`` ``USD``, show a so'm amount as ``amount / uzs_per_usd``
    dollars, marked as approximate - the bill and the payment page are still
    in so'm. With ``UZS``, show so'm as before.
    """

    country: str = Field(
        description='ISO code from the visitor\'s address; `""` unknown.'
    )
    currency: str = Field(description="`UZS` or `USD`.")
    uzs_per_usd: str | None = Field(description="Central Bank rate: so'm per dollar.")
    rate_date: str = Field(description="The bank's date for the rate, `dd.mm.yyyy`.")


class SeatsOfferOut(BaseModel):
    offer: PageOfferOut = Field(
        description="One manager seat; `price_minor` is for 30 days, a purchase "
        "runs to the plan's end (`until`) and costs its share of the days left."
    )
    quotes: list[PageQuoteOut] = Field(description="Empty while not sellable.")
    wallet_minor: int
    max_seats_per_purchase: int
    free: int = Field(description="Free seats: one per page of a paid plan.")
    free_used: int
    paid: int = Field(description="Seats bought and running now.")
    paid_used: int
    waiting: int = Field(description="Managers without a seat.")
    providers: list[Provider]
    payments_on: bool


class PlansOut(PricedChoice):
    subscription: SubscriptionOut | None
    term: TermOut | None
    is_trial: bool
    page_slots: Slots
    page_mix: PageMix
    trial_campaigns: TrialOut | None
    adsets_running: int
    chat: ChatAllowance = Field(description="AI chat questions: today's limit and use.")
    page_offer: PageOfferOut
    page_quotes: list[PageQuoteOut]
    wallet_minor: int
    pending_promo: RedemptionOut | None
    promo_announcement: AnnouncementOut | None
    recent_bills: list[InvoiceOut]
    plans: list[PlanOut]
    featured: str
    providers: list[Provider]
    payments_on: bool
    referral_percent: int
    max_pages_per_purchase: int
    display: DisplayOut


class PaywallOut(PricedChoice):
    already_open: bool = Field(
        False, description="A plan is running; then nothing else comes with it."
    )
    plans: list[PlanOut] = []
    featured: str = ""
    asked: str = ""
    promo_elsewhere: bool | None = Field(
        None, description="A real code, but one to type on the billing screen."
    )
    promo_unknown: str | None = None
    providers: list[Provider] = []
    payments_on: bool = False
    display: DisplayOut | None = None


class HistoryLine(BaseModel):
    kind: str
    move: str
    days: int
    from_plan: PlanOut | None
    to_plan: PlanOut | None
    expires_before: datetime | None
    expires_after: datetime | None
    reason: str
    occurred_at: datetime
    invoice: str
    paid_minor: int
    credit_minor: int
    wallet_minor: int
    discount_minor: int
    price_minor: int


class HistoryOut(BaseModel):
    lines: list[HistoryLine]
    lines_total: int
    invoices: list[InvoiceOut]
    invoices_total: int
    per_page: int


class PromoOut(BaseModel):
    kind: str = Field(
        description="`discount` (applies at checkout) or `grant` (days or pages given)."
    )
    detail: str
    code: str | None = Field(None, description="With `discount`.")
    days: int | None = Field(None, description="With `grant`.")
    pages: int | None = None
    plan_changed: bool | None = None
    pending: bool | None = Field(None, description="Waits for a manager's approval.")


class OkOut(BaseModel):
    ok: bool


class DetailOut(BaseModel):
    detail: str


class InvoiceStatusOut(BaseModel):
    invoice: InvoiceOut
    via: str
    polling: bool = Field(description="Not settled yet: ask again with `tries`.")
    settled: bool
    gave_up: bool
    paid: bool
    just_landed: bool
    tries: int
    poll_seconds: int
    back_url: str = Field(description="Where to send the payer next, if anywhere.")


__all__ = [
    "DetailOut",
    "DisplayOut",
    "HistoryOut",
    "InvoiceStatusOut",
    "OkOut",
    "PaywallOut",
    "PlansOut",
    "PromoOut",
    "SeatsOfferOut",
    "ShownPrices",
    "StatusOut",
]
