"""Response shapes for the office's shell and journal, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.crm.schemas import SettingsOut
from app.modules.supportchat.schemas import ComposerOut, GuestMessageOut
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
    grant: bool = Field(description="Money: payouts, promo codes (Finance, Owner).")
    owner: bool = Field(
        description="The roster, the journal, the payments screen, adding a page, "
        "deleting."
    )
    superuser: bool = Field(
        description="Setting a customer's password, releasing a held bill."
    )
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
    sections: list[str] = Field(description="The office screens they may open.")
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


class BlockOut(BaseModel):
    """The open block: why, whether the customer is told, and by whom."""

    reason: ChoiceOut = Field(description="`value` is the reason's id.")
    shown_to_user: bool
    note: str = Field(description="The office's own note; never shown.")
    blocked_by: PersonOut | None = Field(description="None: blocked before reasons.")
    blocked_at: datetime


class RoleOut(BaseModel):
    """Who the owner said they are at sign-up (`business_owner`, `targetolog`,
    `marketer`, `agency`, `other`)."""

    code: str
    label: str


class SignInOut(BaseModel):
    """A Google (later Telegram, Facebook) account that signs this one in."""

    provider: str
    email: str = Field(description="The provider's address at the last sign-in.")
    linked_at: datetime
    last_used_at: datetime | None


class CustomerRowOut(BaseModel):
    customer: CustomerPersonOut
    role: RoleOut | None = Field(description="None: not asked yet.")
    is_blocked: bool
    is_staff: bool = Field(description="A colleague's own account, for testing.")
    block: BlockOut | None = Field(description="Set while blocked.")
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
    roles: list[ChoiceOut] = Field(
        description="For the `role` filter; `none` is owners not asked yet."
    )


class ProfileOut(CustomerPersonOut):
    language: str
    is_blocked: bool
    is_staff: bool = Field(
        description="A colleague's account: password, block, delete and money "
        "records are refused here (`staff_account`)."
    )
    block: BlockOut | None = Field(description="Set while blocked.")
    joined_at: datetime
    last_login_at: datetime | None
    prepared_at: datetime | None = Field(description="When preparation finished.")
    role: RoleOut | None = Field(description="None: not asked yet.")
    social_only: bool = Field(
        description="No password: signs in only through Google (or the like)."
    )
    sign_ins: list[SignInOut] = Field(description="Google and the like, tied.")


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
    id: str
    refundable: bool = Field(
        False,
        description="A superuser may send its money back from here: a plan bill "
        "paid through a provider that refunds (Rahmat). Always false for others.",
    )
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


class CrmPairLineOut(BaseModel):
    key: str = Field(description="Send as `pair`.")
    page: str
    account: str
    state: str = Field(description="`none`, `draft`, `on` or `off`.")
    cards: int
    managers: int


class CrmTotalsOut(BaseModel):
    """What erasing the CRM takes away, every pair's."""

    setups: int
    stages: int
    reasons: int
    cards: int
    history: int
    managers: int


class CrmStageFigureOut(BaseModel):
    stage_id: str
    cards: int
    won_minor: int


class CrmManagerFigureOut(BaseModel):
    user_id: str
    open: int
    won: int
    won_minor: int


class CrmFiguresOut(BaseModel):
    leads: int = Field(description="Leads this pair's CRM could take.")
    cards: int
    open: int
    won: int
    won_minor: int = Field(description="In the setup's currency.")
    lost: int
    junk: int = Field(description="Cards in the «Sifatsiz lid» column.")
    qualified: int
    late: int = Field(description="Open cards whose due time has passed.")
    today: int = Field(description="Open cards due today.")
    unassigned: int = Field(description="Open cards nobody holds.")
    returned: int
    last_activity_at: datetime | None
    stages: list[CrmStageFigureOut]
    managers: list[CrmManagerFigureOut]


class CustomerCrmOut(SettingsOut):
    pair_lines: list[CrmPairLineOut]
    cards_elsewhere: int = Field(
        description="Cards on pairs the subscription no longer holds: on no board, "
        "gone with the rest when the CRM is erased."
    )
    totals: CrmTotalsOut
    enabled_at: datetime | None
    disabled_at: datetime | None
    seats: UsedOut
    figures: CrmFiguresOut | None = Field(description="Null when there is no pair.")


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
    delivery: str = Field(
        description=(
            "State key: active, paused, pending, billing, rejected, finished, "
            "unknown, stale (the copy says on but is old), no_ads (on, but "
            "every advert is gone), not_read (not mirrored yet). "
            "`delivery_label` is its words."
        )
    )
    is_stale: bool = Field(description="The copy is older than one sweep allows.")
    synced_at: datetime | None = Field(
        description="When Meta was last read for it; null when never."
    )


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
    deleted: int = Field(description="Deleted on Meta; never listed.")
    deleted_totals: list[AmountOut] = Field(
        description="What the deleted ones spent in the window, per currency."
    )
    stale: int = Field(description="Listed rows whose copy is old.")
    refreshing: bool = Field(
        description="A read of Meta was queued now; ask again in ~20 seconds."
    )
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
    objective_label: str
    special_ad_categories: list[str]
    status: str = Field(description="Meta's own status word, as the sync saw it.")
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


class FormQuestionOut(BaseModel):
    label: str
    kind_label: str
    options: list[str]
    by: str = Field(
        description="`ai`, `owner`, `system` (added by the rules), or empty "
        "on a ready form, whose questions nobody here wrote."
    )
    by_label: str


class FormSetupOut(BaseModel):
    origin: str = Field(description="`new`: this launch made it. `ready`: it stood.")
    origin_label: str
    by: str
    by_label: str
    name: str
    higher_intent: bool = Field(description="Meta's review step before sending.")
    depth_label: str
    questions: list[FormQuestionOut] = Field(description="Empty on a ready form.")


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
    form: FormSetupOut | None
    bid_strategy: str = Field(description="As asked at the launch; never mirrored.")
    bid_strategy_label: str
    budget_level: str = Field(description="`campaign` or `adset`.")
    budget_level_label: str
    budget_sharing: bool
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


class FormEndingOut(BaseModel):
    words: str = Field(description="The last screen's button.")
    target: str


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
    created_at: datetime | None
    is_own: bool = Field(description="False: a ready form the launch only pointed at.")
    rows: list[FormQuestionOut]
    ending: FormEndingOut | None


class AdLiveOut(BaseModel):
    status: str
    step: str
    error: str
    delivery_note: str
    qualified: bool
    started_at: datetime | None
    delivery_started_at: datetime | None
    finished_at: datetime | None
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
    optimization_goal_label: str
    billing_event: str
    billing_event_label: str
    destination_type: str
    destination_label: str
    pixel_id: str
    conversion_event: str = Field(description="`promoted_object.custom_event_type`.")
    start_time: datetime | None
    end_time: datetime | None
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


class DirectionOut(BaseModel):
    id: str
    key: str = Field(description="What a profile sends; never edited.")
    label_uz: str
    label_ru: str
    label_en: str
    preset_key: str = Field(description="The catalogue its adverts are built from.")
    preset_label: str
    position: int
    is_active: bool
    businesses: int = Field(description="Profiles on this direction now.")
    created_at: datetime


class DirectionsOut(BaseModel):
    rows: list[DirectionOut]
    presets: list[ChoiceOut] = Field(description="Every `preset_key` allowed.")


class OfficePlanOut(BaseModel):
    id: str
    code: str = Field(
        description="What the cabinet and the site know it by; never edited."
    )
    name: str
    tagline: str
    features: str = Field(description="One line each; `#` a heading, `*` a highlight.")
    price: int = Field(description="Whole so'm.")
    currency: str
    period_days: int
    max_adsets: int = Field(
        description="Shown to the customer, not enforced; 0 is none."
    )
    daily_chat_requests: int = Field(description="0 is no limit.")
    llm_cost_limit_minor: int = Field(
        description="A month, in `llm_currency` cents; 0 is none."
    )
    included_pages: int
    included_google_accounts: int
    extra_page_price: int = Field(description="0 is not sold.")
    crm_seat_price: int = Field(description="0 is not sold.")
    is_one_time: bool
    is_active: bool = Field(description="On sale; off, nobody buys or renews it.")
    sort_order: int
    is_trial: bool = Field(description="The trial runs on this plan's limits.")
    live: int = Field(description="Trial and active subscriptions on it now.")
    deletable: bool = Field(
        description="Nothing points at it; else it is taken off sale."
    )
    created_at: datetime
    updated_at: datetime


class OfficePlansOut(BaseModel):
    rows: list[OfficePlanOut]
    llm_currency: str
    can_edit: bool = Field(description="The superuser alone writes plans.")


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


class RefusalAnswerOut(BaseModel):
    id: str
    key: str = Field(description="Meta's numbers, with what the owner was doing.")
    operation: str
    operation_label: str
    provider_title: str = Field(description="Meta's title for the advertiser.")
    provider_message: str = Field(description="Meta's sentence for the advertiser.")
    answer_uz: str = Field(description="Markdown; `[[name]]` becomes a link.")
    answer_ru: str
    answer_en: str
    written_by: Literal["ai", "office"]
    reviewed: bool = Field(description="A person has read every text on it.")
    held: bool = Field(description="Hidden from owners until the office saves it.")
    retired: bool = Field(description="An old version: hidden until saved.")
    hits: int = Field(description="How many owners met this refusal.")
    created_at: datetime
    edited_at: datetime | None


class RefusalAnswersOut(BaseModel):
    tab: str
    tabs: list[ChoiceOut]
    links: list[ChoiceOut] = Field(description="Names an answer may write in `[[ ]]`.")
    rows: list[RefusalAnswerOut]
    to_review: int = Field(description="Answers waiting for the office, for the badge.")
    total: int
    offset: int
    next_offset: int
    has_more: bool


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


class GuestAccountOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str = Field(description="The phone the account holds.")
    phone_matches: bool = Field(
        description="The guest wrote the account's own phone: check before giving a password back."
    )


class GuestOut(BaseModel):
    id: str = Field(description="`GET /office/support/guests/{id}`.")
    name: str
    phone: str
    email: str
    channel: str = Field(
        "site",
        description="`site` (the sign-in page) or `support_bot`: no phone or email then, the answer goes to Telegram.",
    )
    telegram_username: str = Field(
        "", description="The support bot guest's Telegram handle, without @."
    )
    created_at: datetime
    moved: bool = Field(
        description="Signing in moved it into the account's chat: read-only."
    )
    claimed_by: PersonOut | None


class GuestRowOut(GuestOut):
    waiting: bool = Field(description="The guest spoke last and nobody settled it.")
    last_message_at: datetime | None
    preview: str
    last_side: str = Field(description="`client` (the guest) or `office`.")


class GuestQueueOut(BaseModel):
    state: str
    states: list[ChoiceOut]
    rows: list[GuestRowOut]


class GuestThreadOut(GuestOut):
    waiting: bool
    account: GuestAccountOut | None = Field(
        description="The account behind the guest's email; empty when there is none."
    )
    messages: list[GuestMessageOut]
    guest_read_at: datetime | None = Field(description="The guest's second tick.")
    max_body_chars: int


class SupportBotLinkOut(BaseModel):
    linked: bool = Field(
        description="The client's support bot is live: every reply goes there too."
    )
    username: str = Field(description="Their Telegram handle, without @.")
    last_error: str = Field(
        description="`blocked` or `unreachable`: why replies stopped going."
    )


class SupportThreadOut(BaseModel):
    customer: PersonOut
    support_bot: SupportBotLinkOut | None = Field(
        None,
        description="The client's support-bot chat; empty when they never wrote there.",
    )
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
    block_suggestions: int = Field(
        0, description="Accounts the system asks Support to block."
    )


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


class PaymentTotalsOut(BaseModel):
    earned: list[dict[str, Any]] = Field(
        description="Paid this month, per currency: `currency`, `amount_minor`."
    )
    unpaid: int = Field(description="Open bills, every currency.")
    unpaid_sums: list[dict[str, Any]] = Field(description="The same, per currency.")
    earned_count: int = Field(description="Bills paid this month.")
    earned_before: list[dict[str, Any]] = Field(
        description="Paid last month, per currency."
    )
    stuck: int = Field(description="Attempts holding a bill for over 12 hours.")
    stuck_sums: list[dict[str, Any]] = Field(description="The same, per currency.")
    stuck_after_hours: int
    refunded: int = Field(description="Bills refunded this month.")
    refunded_sums: list[dict[str, Any]] = Field(description="The same, per currency.")


class PaymentHoldOut(BaseModel):
    id: str = Field(description="The attempt; `POST /payments/holds/{id}/release`.")
    number: str
    customer: PersonOut | None = Field(description="Gone when the account was deleted.")
    email: str
    business: str
    plan: str
    provider: str
    amount_minor: int
    currency: str
    created_at: datetime


class PaymentSubscriptionOut(BaseModel):
    id: str
    customer: PersonOut
    plan: PlanLineOut
    status: str
    status_label: str
    state: str = Field(description="`active`, `trial`, `blocked` or `unpaid`.")
    days_left: int
    activated_by: PersonOut | None = Field(description="Who gave it by hand.")
    expires_at: datetime


class PaymentsSummaryOut(BaseModel):
    totals: PaymentTotalsOut
    holds: list[PaymentHoldOut]
    running_out: list[PaymentSubscriptionOut] = Field(
        description="Live subscriptions ending within 7 days, soonest first."
    )


class SurveyTimesOut(BaseModel):
    active: bool
    published_at: datetime | None
    starts_at: datetime | None
    ends_at: datetime | None
    ask_after_days: int = Field(description="Days on a plan before it is asked.")
    phase: str = Field(
        description="`draft`, `scheduled`, `live`, `ended` or `closed`, read now."
    )
    state: str = Field(description="`draft`, `translating`, `ready` or `failed`.")
    created_at: datetime


class SurveyRowOut(SurveyTimesOut):
    id: str
    name: str
    audience: str
    plans: list[str]
    people: int
    questions: int
    answers: int


class SurveyQuestionOut(BaseModel):
    position: int
    kind: str
    text: str
    options: list[str]
    allows_many: bool
    min_value: int | None
    max_value: int | None
    is_required: bool
    show_if: int = Field(description="The earlier question's position; 0: always.")
    show_options: list[int]


class SurveyTabOut(BaseModel):
    code: str
    source: bool
    filled: bool


class SurveyDetailOut(SurveyTimesOut):
    id: str
    name: str
    source_language: str
    title: str
    intro: str
    questions: list[SurveyQuestionOut]
    people: list[str]
    plans: list[str]
    answers: int
    lost: bool = Field(description="The translation has not come back for too long.")
    tabs: list[SurveyTabOut]


class SurveyPersonOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    plan_id: str
    plan: str
    trial: bool


class SurveyPlanOut(BaseModel):
    id: str
    name: str
    total: int


class SurveyRosterOut(BaseModel):
    persons: list[SurveyPersonOut]
    plans: list[SurveyPlanOut]


class WordingQuestionOut(BaseModel):
    position: int
    text: str
    options: list[str]


class SurveyWordingOut(BaseModel):
    title: str
    intro: str
    questions: list[WordingQuestionOut]


class SurveySourceOut(BaseModel):
    title: str
    intro: str
    questions: list[SurveyQuestionOut]


class SurveyTranslationOut(BaseModel):
    language: str
    source: SurveySourceOut
    wording: SurveyWordingOut


class SurveyRefOut(BaseModel):
    id: str
    name: str


class SurveyResponseRowOut(BaseModel):
    id: str
    customer: PersonOut
    survey: SurveyRefOut
    channel: str
    language: str
    gist: str
    replied: bool
    at: datetime


class SurveyResponsesOut(BaseModel):
    rows: list[SurveyResponseRowOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool


class SurveyAnswerLineOut(BaseModel):
    question: str
    kind: str
    answer: str | None


class SurveyResponseOut(SurveyResponseRowOut):
    lines: list[SurveyAnswerLineOut]


class SurveyFunnelOut(BaseModel):
    meant: int = Field(description="Live customers it is for, and who answered.")
    seen: int
    later: int = Field(description="Put it off at least once.")
    answered: int
    rate_percent: float


class SurveyDayOut(BaseModel):
    day: date
    count: int


class SurveyOptionResultOut(BaseModel):
    label: str
    count: int
    percent: float


class SurveyNumberResultOut(BaseModel):
    value: int
    count: int
    percent: float
    low: bool


class SurveyTextResultOut(BaseModel):
    response_id: str
    name: str
    text: str


class SurveyQuestionResultOut(BaseModel):
    position: int
    kind: str
    text: str
    asked: int = Field(description="Reached it: its condition held.")
    answered: int
    options: list[SurveyOptionResultOut]
    numbers: list[SurveyNumberResultOut]
    average: float | None
    min_value: int | None
    max_value: int | None
    texts: list[SurveyTextResultOut] = Field(description="The latest 50.")


class SurveyLowScoreOut(BaseModel):
    response_id: str
    customer_id: str
    name: str
    question: str
    number: int
    max_value: int | None
    replied: bool
    at: datetime


class SurveyResultsOut(BaseModel):
    funnel: SurveyFunnelOut
    days: list[SurveyDayOut]
    channels: dict[str, int]
    languages: dict[str, int]
    questions: list[SurveyQuestionResultOut]
    low_scores: list[SurveyLowScoreOut] = Field(
        description="The lowest 40% of a scale, unanswered first, 50 at most."
    )
    low_total: int


class CustomerSurveyOut(BaseModel):
    id: str
    survey: str
    channel: str
    gist: str
    replied: bool
    at: datetime


class CustomerSurveysOut(BaseModel):
    rows: list[CustomerSurveyOut]


class FeedbackCustomerOut(PersonOut):
    business: str


class FeedbackPieceOut(BaseModel):
    id: str
    customer: FeedbackCustomerOut
    kind: str = Field(description="`text`, `audio` or `video`.")
    text: str
    file_url: str = Field(description="Empty for a text. Needs `?token=` in a player.")
    created_at: datetime
    plan_name: str
    reward_percent: int
    reward_minor: int | None = Field(description="Null: this plan gives no reward.")
    currency: str


class FeedbackDecisionOut(BaseModel):
    id: str
    name: str
    approved: bool
    amount_minor: int
    currency: str
    reason: str
    by: PersonOut | None
    at: datetime


class FeedbackQueueOut(BaseModel):
    rows: list[FeedbackPieceOut]
    recent: list[FeedbackDecisionOut]


class PublishablePieceOut(BaseModel):
    id: str
    customer: FeedbackCustomerOut
    kind: str
    text: str
    file_url: str
    decided_at: datetime


class PublishableOut(BaseModel):
    rows: list[PublishablePieceOut]


class TestimonialOut(BaseModel):
    id: str
    kind: str = Field(description="`image`, `video`, `audio` or `text`.")
    image: str = Field(description="The picture, or a video's cover.")
    video: str
    audio: str
    text: str
    from_customer: bool
    name: str = Field(description="The customer's, on a card from their feedback.")
    business: str
    size_bytes: int | None = Field(description="Null: a file is missing from disk.")
    is_active: bool
    sort_order: int


class PayoutCustomerOut(PersonOut):
    business: str


class PayoutMoneyOut(BaseModel):
    amount_minor: int
    currency: str
    method_label: str
    card_last4: str = Field(description="Empty for a payout recorded by hand.")


class PayoutAskOut(PayoutMoneyOut):
    id: str
    customer: PayoutCustomerOut
    card_number: str | None = Field(
        description="All digits, in fours. Finance and Owner only."
    )
    card_holder: str | None = Field(description="Finance and Owner only.")
    created_at: datetime
    overdue: bool = Field(description="Waiting longer than 48 hours.")


class PayoutQueueOut(BaseModel):
    can_act: bool = Field(description="False for Support: no card, no answers.")
    totals: list[AmountOut] = Field(description="One per currency, never summed.")
    rows: list[PayoutAskOut]


class PayoutRowOut(PayoutMoneyOut):
    id: str
    customer: PayoutCustomerOut
    status: str
    pay_reference: str
    reason: str = Field(description="Why it was turned down or voided.")
    by: PersonOut | None
    at: datetime


class PayoutHistoryOut(BaseModel):
    rows: list[PayoutRowOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool
    states: list[ChoiceOut]
    counts: dict[str, int] = Field(description="Rows per state, inside the search.")


class PaymentTransactionOut(BaseModel):
    id: str = Field(description="What `tools/erase_payment.py` takes.")
    provider: str
    external_id: str
    state: str


class InvoiceArchiveOut(BaseModel):
    at: datetime
    by: PersonOut | None
    reason: str


class PaymentInvoiceOut(CardInvoiceOut):
    id: str
    customer: PersonOut | None = Field(description="Gone when the account was deleted.")
    email: str
    archive: InvoiceArchiveOut | None = Field(
        description="Who took it off the books; `null` for a bill still on them."
    )
    transaction: PaymentTransactionOut | None = Field(
        description="The last attempt to pay; `null` for a bill written by hand."
    )
    refundable: bool = Field(
        description="Paid through a provider that can be asked from here to send"
        " the money back (Rahmat), for a plan alone - pages and seats bought"
        " with it would stay: `POST /invoices/{id}/refund` takes it."
    )


class PaymentInvoicesOut(BaseModel):
    rows: list[PaymentInvoiceOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool
    states: list[ChoiceOut]
    counts: dict[str, int] = Field(description="Bills per chip, inside the search.")


class PaymentSubscriptionsOut(BaseModel):
    rows: list[PaymentSubscriptionOut]
    total: int
    offset: int
    next_offset: int
    has_more: bool
    states: list[ChoiceOut]
    counts: dict[str, int] = Field(description="Rows per chip, inside the search.")


class StaffMemberOut(BaseModel):
    id: str
    name: str
    email: str
    roles: list[str] = Field(description="Every role for a super admin.")
    superuser: bool
    is_me: bool


class StaffTeamOut(BaseModel):
    members: list[StaffMemberOut]


class StaffBotLinkOut(BaseModel):
    account: str = Field(description="`@username`, or the chat id without one.")
    linked_at: datetime


class StaffBotTopicOut(BaseModel):
    topic: str
    roles: list[str]


class StaffBotOut(BaseModel):
    configured: bool = Field(description="False: the bot has no token on this server.")
    username: str
    link: StaffBotLinkOut | None
    roles: list[str]
    topics: list[StaffBotTopicOut] = Field(
        description="What the bot sends this reader; empty for a role it has nothing for."
    )


class StaffBotUrlOut(BaseModel):
    url: str


class FacebookHoldingsOut(BaseModel):
    """What disconnecting Facebook would take away; the subscription, its
    extra pages and the bought seats are not on the list because they stay."""

    connected: bool
    pages: int
    ad_accounts: int
    pixels: int
    launches: int
    campaigns: int
    leads: int
    cards: int
    managers: int = Field(description="CRM managers; their logins go too.")
    audiences: int = Field(description="Ours only; Meta keeps them.")
    brand_kits: int


class FacebookForgottenOut(MessageOut):
    rows: dict[str, int]
    kept_business: bool = Field(
        description="A business profile was kept pageless for the next page."
    )


class SignalCountsOut(BaseModel):
    sent: int
    pending: int
    failed: int
    expired: int


class SignalDayOut(BaseModel):
    day: date = Field(description="The owner's own day.")
    state: Literal["unsent", "sent", "partly", "lost", "empty"] = Field(
        description="`unsent`: rows the button would send; `partly`: some sent, "
        "some refused or past the window; `lost`: none went and none can."
    )
    sendable: int
    sent_at: datetime | None
    datasets: list[str] = Field(description="Pixels the sent rows went into.")
    errors: list[str] = Field(description="Meta's refusals, three at most.")
    stages: dict[str, SignalCountsOut] = Field(
        description="`received`, `qualified`, `unqualified`, `converted`."
    )


class SignalBlockerOut(BaseModel):
    account: str
    name: str
    reason: Literal["connection", "no_pixel"]


class SignalBookOut(BaseModel):
    sendable: int = Field(description="Rows of finished days the button sends.")
    last_sent_at: datetime | None
    next_night: datetime
    window_days: int
    blockers: list[SignalBlockerOut] = Field(
        description="Why a waiting account would fail again, read now."
    )
    days: list[SignalDayOut]


class SignalsSentOut(MessageOut):
    sent: int
    waiting: int = Field(description="Still unsent afterwards.")


class ActivityRowOut(BaseModel):
    id: str = Field(description="`<source>:<uuid>`.")
    source: Literal["action", "event", "office"]
    at: datetime
    group: str = Field(description="One of `groups`.")
    title: str
    text: str
    who: str = Field(
        description="`customer`, `manager`, `system`, `agent`, `staff`; "
        "empty when the log does not say."
    )
    who_name: str
    status: str = Field(description="`applied`, `failed`, `pending`, `reverted`.")
    status_label: str
    error: str
    detail: dict[str, Any] = Field(
        description="An action's `request`/`before`/`result`; an event's payload; "
        "an office row's detail."
    )


class ActivityOut(BaseModel):
    groups: list[ChoiceOut]
    who: list[ChoiceOut]
    rows: list[ActivityRowOut]
    next_before: datetime | None = Field(
        description="Send as `before` for the next page; empty at the end."
    )


class BlockReasonOut(BaseModel):
    id: str
    code: str | None = Field(description="Set on the reasons the system names.")
    name: str
    message_uz: str
    message_ru: str
    message_en: str
    position: int
    is_archived: bool
    is_system: bool = Field(description="Its words may change; it cannot be archived.")


class BlockReasonsOut(BaseModel):
    rows: list[BlockReasonOut]
    may_edit: bool = Field(description="The superuser keeps the list.")


class SuggestionDetailOut(BaseModel):
    external_user_id: str = Field(description="The Facebook or Google id reused.")
    held_by: PersonOut | None = Field(description="The cabinet that already has it.")


class ReasonLineOut(BaseModel):
    id: str
    name: str


class BlockSuggestionOut(BaseModel):
    id: str
    customer: CustomerPersonOut
    reason: ReasonLineOut
    times: int = Field(description="How often the system refused it.")
    first_at: datetime
    last_at: datetime
    detail: SuggestionDetailOut


class BlockSuggestionsOut(BaseModel):
    rows: list[BlockSuggestionOut]
    total: int
