"""Response shapes for the office's shell and journal, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonOut(BaseModel):
    id: str
    name: str
    email: str


class ChoiceOut(BaseModel):
    value: str
    label: str


class CanOut(BaseModel):
    give: bool = Field(
        description="Plan, days, slots, a payment, the referral switch "
        "(Support, Finance, Owner)."
    )
    grant: bool = Field(
        description="Money: payouts, holds, promo codes (Finance, Owner)."
    )
    owner: bool = Field(description="The roster, the journal, adding a page, deleting.")
    superuser: bool = Field(description="Setting a customer's password.")
    engineer: bool = Field(description="The faults console.")
    answer_support: bool = Field(description="The support chat queue.")
    answer_feedback: bool = Field(description="The feedback queue.")
    sell: bool = Field(description="The sales board.")
    lead_sales: bool = Field(description="The sales lead's screens: holds, settings.")


class WaitingOut(BaseModel):
    """Counts beside the rail's entries; 0 for a door this reader lacks."""

    promos: int
    asks: int = Field(description="Withdrawal requests waiting to be paid.")
    feedback: int
    support: int = Field(description="Chats whose customer spoke last.")
    arizas: int = Field(description="Home page call-back requests in the sales queue.")


class MeOut(BaseModel):
    user: PersonOut
    roles: list[ChoiceOut] = Field(description="The roles this reader holds.")
    can: CanOut
    waiting: WaitingOut


class TraceOut(BaseModel):
    id: str
    created_at: datetime
    kind: str
    kind_label: str
    reason: str
    detail: dict[str, Any]
    actor: PersonOut | None = Field(description="Gone when that member was removed.")


class JournalRowOut(TraceOut):
    customer: PersonOut


class JournalOut(BaseModel):
    kind: str
    kinds: list[ChoiceOut] = Field(
        description='Filter chips; `""` is every write, readings come last.'
    )
    rows: list[JournalRowOut]
    offset: int
    next_offset: int
    has_more: bool


# -- customers ---------------------------------------------------------------------


class AmountOut(BaseModel):
    currency: str
    amount_minor: int


class CustomerPersonOut(PersonOut):
    phone: str


class BusinessLineOut(BaseModel):
    name: str
    direction: str = Field(description="The business type, in Uzbek.")


class PlanLineOut(BaseModel):
    code: str
    name: str


class TermOut(BaseModel):
    state: str = Field(
        description="`trial`, `active` (live), `lapsed` (paid once, ended) or "
        "`never` (no subscription ever)."
    )
    label: str
    plan: PlanLineOut | None = Field(description="Live plan, else the last one.")
    days_left: int | None = Field(description="Live only; 0 is today.")
    expires_at: datetime | None = Field(description="Live only.")
    ended_on: datetime | None = Field(description="Lapsed only.")


class TroubleOut(BaseModel):
    kind: str = Field(
        description="`connection`, `account_blocked`, `payment_due`, `lead_gap`, "
        "`sweep`, `launch`, `hold`, `expiring`, `setup`."
    )
    label: str
    what: str
    urgent: bool
    since: datetime | None


class PagesOut(BaseModel):
    used: int
    allowed: int | None = Field(description="None without a live plan.")


class CustomerRowOut(BaseModel):
    customer: CustomerPersonOut
    is_blocked: bool
    joined_at: datetime
    last_login_at: datetime | None
    business: BusinessLineOut | None
    term: TermOut
    trouble: TroubleOut | None = Field(description="The worst thing wrong.")
    pages: PagesOut | None
    running: int = Field(description="Campaigns this product launched, running now.")
    spend: list[AmountOut] = Field(description="This month, per currency.")
    leads: int = Field(description="This month's applications.")
    paid_total: list[AmountOut] = Field(description="Every paid bill, per currency.")
    paid_before: bool = Field(
        description="A deleted account on this address left paid receipts behind."
    )
    sales_manager: PersonOut | None


class CustomersOut(BaseModel):
    rows: list[CustomerRowOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool
    as_of: datetime = Field(description="Send back as `as_of` with the next offset.")
    states: list[ChoiceOut]
    sorts: list[ChoiceOut]
    plans: list[ChoiceOut]
    managers: list[ChoiceOut] = Field(
        description="Sales staff, for the `manager` filter; `none` is nobody's."
    )


class ProfileOut(CustomerPersonOut):
    language: str
    is_blocked: bool
    joined_at: datetime
    last_login_at: datetime | None
    prepared_at: datetime | None = Field(description="When preparation finished.")


class BusinessOut(BaseModel):
    id: str
    name: str
    direction: str
    page_id: str | None
    city: str
    country_code: str
    contact_phone: str
    website: str


class SubscriptionOut(BaseModel):
    plan: PlanLineOut | None
    status: str
    status_label: str
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None
    days_left: int | None = Field(description="Live only; 0 is today.")
    extra_pages: int
    setup_completed_at: datetime | None
    activated_by: PersonOut | None
    note: str


class UsedOut(BaseModel):
    used: int
    allowed: int = Field(description="0 is no limit.")


class RunningOut(BaseModel):
    about: str = Field(description="The page, when there are several.")
    used: int


class AiOut(BaseModel):
    spent_minor: int
    limit_minor: int
    currency: str
    entitled: bool = Field(description="False: no live plan, never granted.")


class LimitsOut(BaseModel):
    pages: UsedOut
    extra_instagrams: int = Field(description="Of `pages.used`, Instagram slots.")
    crm_seats: UsedOut
    running: list[RunningOut] = Field(description="Ad groups delivering, per page.")
    ai: AiOut = Field(description="This month's assistant budget.")
    chat: UsedOut = Field(description="Today's assistant questions.")
    trial_left: int | None = Field(description="Trial launches left; None when paid.")
    has_plan: bool


class PlanChoiceOut(BaseModel):
    code: str
    name: str
    is_active: bool = Field(description="False: withdrawn from sale.")
    currency: str
    due_minor: int = Field(description="What the customer would owe: the amount box.")
    waits: bool = Field(description="Cheaper than the running plan: not until it ends.")


class PlanPickerOut(BaseModel):
    choices: list[PlanChoiceOut]
    credit_minor: int = Field(description="The unused paid days a change takes off.")
    credit_days: int
    currency: str


class MetaOut(BaseModel):
    status: str
    status_label: str
    name: str = Field(description="The Facebook profile's name.")
    expires_at: datetime | None
    last_verified_at: datetime | None
    last_error_code: str
    action_required: bool = Field(description="Meta asks the customer to confirm.")
    connected_at: datetime


class AdAccountOut(BaseModel):
    id: str
    external_id: str
    name: str
    currency: str
    is_active: bool = Field(description="Chosen in the cabinet.")
    may_advertise: bool | None
    payment_due: bool | None
    balance_minor: int
    synced_at: datetime | None


class PairOut(BaseModel):
    ad_account_id: str
    ad_account_name: str
    stored: bool = Field(description="False: drawn by default, nobody chose it yet.")


class InstagramOut(BaseModel):
    name: str
    is_own: bool = Field(description="The page's own account, on the page's slot.")
    in_subscription: bool
    is_linked: bool = Field(description="False: Meta unlinked it from the page.")


class PageOut(BaseModel):
    id: str
    external_id: str
    name: str
    is_active: bool = Field(description="In the subscription.")
    leadgen_subscribed: bool
    may_advertise: bool | None
    live_groups: int
    pairs: list[PairOut]
    instagrams: list[InstagramOut]


class PixelOut(BaseModel):
    external_id: str
    name: str
    is_active: bool


class TelegramOut(BaseModel):
    username: str
    is_active: bool
    linked_at: datetime | None
    last_error_at: datetime | None


class AgentOut(BaseModel):
    is_enabled: bool
    last_run_at: datetime | None


class CardInvoiceOut(BaseModel):
    number: str
    kind: str
    kind_label: str
    status: str
    status_label: str
    plan: PlanLineOut | None
    amount_minor: int = Field(description="Money paid, Hamyon and credit left out.")
    wallet_minor: int
    credit_minor: int
    currency: str
    period_days: int
    pages: int
    seats: int
    manual_method: str = Field(description="Set when the office wrote it down.")
    recorded_by: PersonOut | None
    created_at: datetime
    paid_at: datetime | None


class HistoryLineOut(BaseModel):
    kind: str
    kind_label: str
    from_plan: PlanLineOut | None
    to_plan: PlanLineOut | None
    days: int
    expires_before: datetime | None
    expires_after: datetime | None
    invoice: str
    paid_minor: int
    actor: PersonOut | None
    reason: str
    occurred_at: datetime


class MoneyOut(BaseModel):
    paid: list[AmountOut]
    invoices: list[CardInvoiceOut] = Field(description="The latest 6.")
    history: list[HistoryLineOut] = Field(description="The latest 10.")
    old_receipts: list[CardInvoiceOut] = Field(
        description="A deleted account on this address paid these; attach, "
        "do not write the money down twice."
    )


class WalletOut(BaseModel):
    currency: str
    earned_minor: int
    paid_minor: int
    spent_minor: int
    held_minor: int
    available_minor: int


class PayoutOut(BaseModel):
    id: str
    status: str
    status_label: str
    amount_minor: int
    currency: str
    method: str
    card_last4: str
    created_at: datetime
    decided_at: datetime | None


class ReferralOut(BaseModel):
    mode: str = Field(description="`auto`, `open` or `closed`.")
    mode_label: str
    mode_reason: str
    mode_set_by: PersonOut | None
    open: bool = Field(description="Whether the link works and earns.")
    wallet_payable: bool
    inviter: PersonOut | None
    invited: int
    wallet: list[WalletOut]
    payouts: list[PayoutOut] = Field(description="The latest 6.")


class CardSalesOut(BaseModel):
    claim: dict[str, Any] | None = Field(
        description="The open sales card, as the sales board draws it."
    )
    closed: int
    lines: list[dict[str, Any]] = Field(description="The latest 10 sales notes.")
    hold: dict[str, Any] | None = Field(description="A do-not-call hold.")


class CustomerCardOut(BaseModel):
    profile: ProfileOut
    businesses: list[BusinessOut]
    subscription: SubscriptionOut | None
    lapsed: SubscriptionOut | None = Field(
        description="The last one, when none is live."
    )
    limits: LimitsOut
    plan_picker: PlanPickerOut
    meta: MetaOut | None
    ad_accounts: list[AdAccountOut]
    pages: list[PageOut]
    pixels: list[PixelOut]
    telegram: TelegramOut | None
    agent: AgentOut | None
    money: MoneyOut
    referral: ReferralOut
    sales: CardSalesOut
    problems: list[TroubleOut]
    traces: list[TraceOut] = Field(description="The office's last 6 actions here.")


class MessageOut(BaseModel):
    message: str = Field(description="What happened, to show in the message strip.")


class DeletedOut(MessageOut):
    rows: int
    receipts_kept: int


class AdRowOut(BaseModel):
    launch_id: str
    campaign_external_id: str
    started_at: datetime | None
    goal: str
    page: str
    delivery_label: str
    is_running: bool
    spend_minor: int
    currency: str
    results: int = Field(description="What it was bought for: leads, calls, chats...")
    result_word: str
    result_cost_minor: int | None
    result_cost_label: str
    note: str = Field(description="Instead of a figure this screen cannot count.")


class CustomerAdsOut(BaseModel):
    period: str
    periods: list[ChoiceOut]
    running: int = Field(description="Delivering now, whatever the window.")
    totals: list[AmountOut] = Field(description="Spend per currency, never summed.")
    hidden: int = Field(description="Adverts left out: quiet over this window.")
    rows: list[AdRowOut]
