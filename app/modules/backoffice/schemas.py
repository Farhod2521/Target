"""Response shapes for the office's shell and journal, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.supportchat.schemas import ComposerOut
from app.modules.supportchat.schemas import MessageOut as ChatMessageOut


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
    campaign_name: str
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
    impressions: int
    reach: int | None = Field(description="Null when nobody counted this window.")
    clicks: int
    link_clicks: int
    leads: int
    ctr_percent: str = Field(description="Empty before the first impression.")
    cpm_minor: int | None
    cpc_minor: int | None


class AdWindowOut(BaseModel):
    period: str
    since: date
    until: date
    refused: str = Field(description="Why a typed stretch was not read; else empty.")
    periods: list[ChoiceOut]


class AdCurrencyOut(BaseModel):
    currency: str
    spend_minor: int
    impressions: int
    clicks: int
    link_clicks: int
    leads: int
    ctr_percent: str
    cpm_minor: int | None
    cpc_minor: int | None
    lead_cost_minor: int | None


class CustomerAdsOut(BaseModel):
    period: str
    periods: list[ChoiceOut]
    window: AdWindowOut
    running: int = Field(description="Delivering now, whatever the window.")
    totals: list[AmountOut] = Field(description="Spend per currency, never summed.")
    summary: list[AdCurrencyOut] = Field(description="All figures, one per currency.")
    hidden: int = Field(description="Adverts left out: quiet over this window.")
    rows: list[AdRowOut]


class AdSumsOut(BaseModel):
    spend_minor: int
    impressions: int
    clicks: int
    link_clicks: int
    landing_page_views: int
    leads_reported: int = Field(description="The provider's count.")
    results_reported: int
    recallers: int
    profile_visits: int
    video_plays: int
    video_thruplays: int
    reactions: int
    comments: int
    shares: int
    saves: int
    ctr_percent: str
    cpm_minor: int | None
    cpc_minor: int | None


class AdResultOut(BaseModel):
    label: str = Field(description="Empty for a result this screen cannot count.")
    count: int
    cost_minor: int | None
    cost_label: str
    note: str


class AdBarOut(BaseModel):
    key: date
    label: str
    hint: str
    sums: AdSumsOut
    reach: int = Field(description="The widest day: at least this many people.")
    leads: int
    qualified: int
    results: int
    result_cost_minor: int | None


class AdLifetimeLeadsOut(BaseModel):
    total: int
    tests: int
    organic: int
    first_at: datetime | None
    last_at: datetime | None


class AdFiguresOut(BaseModel):
    sums: AdSumsOut
    reach: int
    reach_is_exact: bool = Field(description="False: at least this many people.")
    result: AdResultOut
    leads: int
    qualified: int
    synced_at: datetime | None
    lifetime_leads: AdLifetimeLeadsOut


class AdCampaignOut(BaseModel):
    external_id: str
    name: str
    objective: str
    delivery_label: str
    is_running: bool
    daily_budget_minor: int | None
    spend_cap_minor: int | None
    currency: str
    created_at: datetime | None
    problem: str


class AudienceOut(BaseModel):
    places: list[str]
    excluded_places: list[str]
    ages: str
    genders: str
    interests: list[list[str]] = Field(description="Blocks: AND between, OR within.")
    excluded_interests: list[str]
    placements: list[str] = Field(description="Empty: the provider chooses.")
    devices: list[str]
    own_lists: list[str]
    excluded_lists: list[str]
    is_automatic: bool


class AdDecisionOut(BaseModel):
    key: str = Field(
        description="`campaign_type`, `conversion_event`, `audience`, `interests`, "
        "`placement`, `form` or `button`."
    )
    label: str
    value: str
    by: str = Field(description="`ai`, `owner`, or empty when it was not recorded.")
    by_label: str


class LaunchAdOut(BaseModel):
    id: str
    position: int
    name: str
    headline: str
    text: str
    description: str
    words_by: str = Field(description="`ai`, `owner`, or empty: no words of its own.")
    words_by_label: str
    picture: str
    is_video: bool
    video_url: str
    media_kind_label: str
    post_url: str = Field(description="The post it was built from; empty for none.")


class AdSettingsOut(BaseModel):
    goal: str
    goal_text: str = Field(description="The customer's own words about the goal.")
    offer_text: str
    link_url: str
    phone: str
    campaign_name: str
    created_at: datetime
    page: str
    currency: str
    daily_budget_minor: int | None
    daily_min_minor: int | None
    daily_max_minor: int | None
    total_cap_minor: int | None
    max_result_cost_minor: int | None
    start_date: date | None
    end_date: date | None
    audience_lower: int | None
    audience_upper: int | None
    audience: AudienceOut
    button: str
    conversion_event: str
    url_tags: str
    attribution: str
    frequency_cap: dict[str, int] | None
    buys_qualified_leads: bool
    decisions: list[AdDecisionOut] = Field(description="Who settled each part.")
    ads: list[LaunchAdOut]


class AdPostOut(BaseModel):
    external_id: str
    url: str = Field(description="Empty when this post has no address we know.")
    kind_label: str
    text: str
    picture: str


class LiveAdOut(BaseModel):
    external_id: str
    name: str
    delivery: str
    delivery_label: str
    problem: str
    picture: str
    is_video: bool
    video_url: str
    text: str
    headline: str
    description: str
    link: str
    button: str
    post: AdPostOut | None


class LiveFormOut(BaseModel):
    external_id: str
    is_synced: bool = Field(description="False: only the id is known so far.")
    name: str
    questions: list[str]
    custom_questions: list[dict[str, Any]]
    leads_count: int | None
    collecting: bool
    privacy_url: str
    locale: str


class AdLiveOut(BaseModel):
    status: str
    step: str
    error: str
    delivery_note: str
    qualified: bool
    ads: list[LiveAdOut]
    forms: list[LiveFormOut]


class AdLineOut(BaseModel):
    external_id: str
    name: str
    delivery_label: str
    quality_ranking: str
    sums: AdSumsOut
    leads: int
    lead_cost_minor: int | None


class AdGroupOut(BaseModel):
    external_id: str
    name: str
    delivery_label: str
    optimization_goal: str
    daily_budget_minor: int | None
    is_learning: bool
    problem: str
    audience: AudienceOut | None = Field(description="As the last sync saw it.")
    sums: AdSumsOut
    leads: int
    lead_cost_minor: int | None
    ads: list[AdLineOut]


class AdSiblingOut(BaseModel):
    launch_id: str
    started_at: datetime


class CustomerAdOut(BaseModel):
    launch_id: str
    window: AdWindowOut
    bar: str = Field(description="`day`, `week` or `month`: the size of one bar.")
    bars_offered: list[ChoiceOut]
    row: AdRowOut | None = Field(description="Null: the launch made no campaign.")
    campaign: AdCampaignOut | None
    figures: AdFiguresOut | None
    bars: list[AdBarOut] = Field(description="Oldest first.")
    groups: list[AdGroupOut]
    siblings: list[AdSiblingOut] = Field(description="Launches in the same campaign.")
    settings: AdSettingsOut
    live: AdLiveOut


class AdFrameOut(BaseModel):
    src: str = Field(description="Meta's preview address, for an iframe.")
    width: int
    height: int
    polling: bool = Field(description="Ask again in `poll_seconds` with `tries`.")
    tries: int
    poll_seconds: int
    gave_up: bool


class CreatedOut(MessageOut):
    id: str


class PromoPlanOut(BaseModel):
    code: str
    name: str


class PromoCodeOut(BaseModel):
    id: str
    code: str
    kind: str = Field(description="`plan`, `slots` or `discount`; never edited.")
    kind_label: str
    description: str
    is_active: bool
    status: str = Field(description="`live`, `scheduled`, `spent`, `expired`, `off`.")
    status_label: str
    used: int = Field(description="Uses spent; a waiting request counts.")
    percent: int = Field(description="How full against `max_uses`; 0 = no ceiling.")
    starts_at: datetime | None
    expires_at: datetime | None
    max_uses: int
    max_uses_per_user: int
    note: str
    grant_days: int
    plan: PromoPlanOut | None
    grant_pages: int
    needs_approval: bool
    discount_kind: str
    discount_value: int = Field(description="A percent, or whole units for `amount`.")
    scope: str
    min_amount: int = Field(description="Whole units of `currency`.")
    created_at: datetime


class PromoOffersOut(BaseModel):
    days: int
    pages: int
    plan: str


class PromoRequestOut(BaseModel):
    id: str
    customer: PersonOut
    code: str
    kind: str
    kind_label: str
    description: str
    offers: PromoOffersOut = Field(description="What the code gives as it reads now.")
    redeemed_at: datetime
    refused_before: int = Field(
        description="This person's earlier refusals; queue only."
    )
    status: str
    status_label: str
    decided_at: datetime | None
    decided_by: PersonOut | None
    decision_note: str


class PromoOut(BaseModel):
    tab: str
    requests: list[PromoRequestOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool
    current: list[PromoCodeOut] = Field(description="Live, or written in advance.")
    finished: list[PromoCodeOut] = Field(description="Off, expired, or used up.")
    currency: str = Field(description="What fixed discounts and `min_amount` are in.")
    kinds: list[ChoiceOut]
    discount_kinds: list[ChoiceOut]
    scopes: list[ChoiceOut]
    plans: list[ChoiceOut]


class SupportRowOut(BaseModel):
    id: str = Field(description="The chat's id: `GET /office/support/{id}`.")
    customer: PersonOut
    waiting: bool = Field(description="The client spoke last and nobody settled it.")
    last_message_at: datetime | None
    last_client_at: datetime | None
    preview: str = Field(description="The last message in one line.")
    last_side: str = Field(description="`client` or `office`: who wrote it.")


class SupportQueueOut(BaseModel):
    state: str
    states: list[ChoiceOut]
    rows: list[SupportRowOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool


class SupportThreadOut(BaseModel):
    customer: PersonOut
    conversation_id: str | None = Field(
        description="Empty: no chat yet; the first message writes it."
    )
    waiting: bool
    messages: list[ChatMessageOut]
    page: int
    pages: int
    has_previous: bool
    has_next: bool
    client_read_at: datetime | None = Field(description="The client's second tick.")
    send_key: str
    ws_path: str = Field(description="Add `?token=`; empty without a chat.")
    composer: ComposerOut


class WindowOut(BaseModel):
    period: str
    unit: str = Field(description="One bar: `day`, `week` or `month`.")
    since: date
    until: date
    days: int
    refused: str = Field(description="Why a typed range was not used; else empty.")
    periods: list[ChoiceOut]


class PlanShareOut(BaseModel):
    name: str
    payments: int
    amount_minor: int
    share_pct: int = Field(description="Of the amount.")


class SliceOut(BaseModel):
    amount_minor: int
    payments: int
    signups: int
    average_minor: int
    online_minor: int
    manual_minor: int
    plans: list[PlanShareOut]


class BarOut(BaseModel):
    key: str = Field(description="Pass as `bar` to read its figures.")
    label: str
    hint: str
    height_pct: int
    is_current: bool = Field(description="Today is in it: not finished yet.")
    amount_minor: int
    payments: int
    signups: int


class TakingsOut(BaseModel):
    window: WindowOut
    currency: str
    bars: list[BarOut]
    picked: str
    shown: SliceOut = Field(description="The picked bar, or the whole window.")
    before_minor: int = Field(description="The same number of days just before.")
    change_pct: int | None
    unpaid: int = Field(description="Bills waiting to be paid, now.")
    unpaid_minor: int
    given_free: int = Field(description="Plans, days, pages the office gave free.")


class DashCustomersOut(BaseModel):
    total: int
    joined: int
    joined_before: int
    joined_change_pct: int | None
    trial: int = Field(description="On a trial now.")
    paying: int = Field(description="On a paid plan now.")
    expiring: int = Field(description="Ending within 7 days.")
    churned: int = Field(description="Stopped in the window and not back.")
    joined_paid: int = Field(description="Of those who joined, how many paid.")
    conversion_pct: int | None
    setup_unfinished: int
    meta_missing: int = Field(description="Subscribed, no live Facebook link.")


class DashActivityOut(BaseModel):
    running: int
    launched: int
    failed: int
    spend: list[AmountOut] = Field(description="Customers' ad spend, per currency.")
    leads: int
    leads_before: int
    leads_change_pct: int | None
    ai_cost: AmountOut | None = Field(description="Money roles only.")


class DashWaitingOut(BaseModel):
    promos: int
    support: int
    support_oldest: datetime | None = Field(description="The longest-waiting chat.")
    asks: int
    feedback: int
    arizas: int
    holds: int = Field(description="Payments held longer than 12 hours.")


class DashProblemOut(BaseModel):
    kind: str
    label: str
    urgent: bool
    customer_id: str | None
    who: str
    what: str
    since: datetime | None
    action: str


class DashProblemsOut(BaseModel):
    total: int
    urgent: int
    rows: list[DashProblemOut]


class DashPaymentOut(BaseModel):
    paid_at: datetime
    customer: PersonOut | None = Field(description="Gone when the account was deleted.")
    email: str
    plan: str
    amount_minor: int
    currency: str
    manual: bool


class DashSalesOut(BaseModel):
    manager: PersonOut
    sold: int = Field(description="Sold in the window.")
    open: int = Field(description="Cards open now.")


class DashboardOut(BaseModel):
    window: WindowOut
    sees_money: bool
    takings: TakingsOut | None = Field(description="Money roles only.")
    customers: DashCustomersOut
    activity: DashActivityOut
    waiting: DashWaitingOut
    problems: DashProblemsOut
    payments: list[DashPaymentOut] | None = Field(description="Money roles only.")
    sales: list[DashSalesOut]
