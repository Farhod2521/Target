from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.telephony.schemas import CallOut


class PersonOut(BaseModel):
    id: str
    name: str
    email: str


class RoleOut(BaseModel):
    value: str
    label: str


class BoardOut(BaseModel):
    code: str = Field(description="`sales`, `support` or `renewal`.")
    label: str
    lead: bool = Field(description="Sees the whole board and gives cards out.")


class CanOut(BaseModel):
    take: bool = Field(description="Has the «Lid olish» button.")
    take_ticket: bool = Field(description="Has the «Zayavka olish» button.")
    assign: bool = Field(description="Gives a card to somebody else.")
    move: bool = Field(description="Moves a card to any column.")
    add_lead: bool = Field(description="Puts a client on the Sales board by hand.")
    add_ticket: bool = Field(description="Opens a Support ticket by hand.")
    columns: bool = Field(
        description="Opens the boards' settings and reads the columns there."
    )
    edit_columns: bool = Field(
        False,
        description="The superuser: renames and reorders columns, adds their "
        "own and takes those off.",
    )
    staff: bool = Field(description="Adds staff and gives roles.")
    telephony: bool = Field(description="Opens the telephony settings.")
    client_card: bool = Field(
        False,
        description="May open the client's office card; hide its link otherwise.",
    )
    renewal_manager: bool = Field(
        False, description="Picks the renewal board's default manager."
    )


class MeOut(BaseModel):
    user: PersonOut
    roles: list[RoleOut]
    is_superuser: bool
    boards: list[BoardOut] = Field(description="Empty: no board for this person.")
    default_board: str | None = Field(description="The board to open first.")
    can: CanOut


class ColumnOut(BaseModel):
    code: str = Field(description="Never changes; cards move by it.")
    name: str
    position: int
    kind: str = Field(
        description="`manual`: a button moves cards here; `auto`: what happened to the client does."
    )
    is_final: bool
    is_default_name: bool = Field(
        True,
        description="The name it was seeded with: a screen in another language "
        "names it by `code`. False once the office renamed it.",
    )
    is_custom: bool = Field(
        False,
        description="Added by the superuser. No rule and no button moves cards "
        "here: only `POST /cards/{id}/move`. Only these may be taken off.",
    )


class ColumnsOut(BaseModel):
    board: str
    live_since: datetime | None = Field(
        description="Sign-ups and events before it are not on the board."
    )
    columns: list[ColumnOut]
    removed: list[ColumnOut] = Field(
        default_factory=list,
        description="The superuser's columns taken off the board: a card's "
        "history may still name them, and the superuser may put them back.",
    )
    may_edit: bool = Field(
        False, description="This person may change the columns (the superuser)."
    )
    max_columns: int = Field(20, description="A board shows at most this many.")


class ClientOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    signed_up_at: datetime
    signup_via: str = Field(
        "",
        description="How the account was opened: `email`, `google`, `telegram`; empty: not known.",
    )
    signup_via_label: str = Field("", description="The same in words.")
    utm: dict[str, str] = Field(
        default_factory=dict,
        description="The landing link's marks before signing up: `source`, "
        "`medium`, `campaign`, `content`, `term` (each only when there was one).",
    )


class ReasonChipOut(BaseModel):
    code: str
    label: str


class CardOfferOut(BaseModel):
    percent: int = Field(description="20, then 10; 0 once the discount is over.")
    started_at: datetime = Field(
        description="When the discount started: the Start payment, or the "
        "manager's «Gaplashildi»."
    )
    ends_at: datetime | None = Field(description="When this percent ends.")
    source: str = Field(
        "contact",
        description="`start`: the client paid Start. `contact`: the manager "
        "talked to a lead who has not.",
    )
    next_percent: int = Field(0, description="The percent after `ends_at`; 0: none.")
    next_ends_at: datetime | None = Field(
        None,
        description="When `next_percent` ends: the card goes to Bog'lanildi then.",
    )


class RenewalMoneyOut(BaseModel):
    currency: str
    minor: int


class CardRenewalOut(BaseModel):
    plan_code: str = Field(description="`standart` or `pro`.")
    plan_name: str
    term_ends_at: datetime
    ended: bool = Field(description="The term is over.")
    days: int = Field(
        description="Days to the term's end; negative: days since it ended."
    )
    pages: list[str] = Field(description="The client's pages, the current first.")
    ads_running: int
    leads_month: int = Field(description="Applications this month.")
    spend_month: list[RenewalMoneyOut] = Field(description="Ad spend this month.")
    payments: int = Field(description="Plan bills the client has paid, ever.")
    last_login: datetime | None
    decline_reason: str = Field(description="Empty unless the card is in Rad etdi.")
    decline_label: str
    paid: RenewalMoneyOut | None = Field(description="The bill that renewed the term.")


class CardHeatOut(BaseModel):
    level: str = Field(description="`hot`, `warm` or `cold`.")
    label: str = Field(description="«Issiq», «Iliq», «Sovuq».")
    points: int = Field(description="What «Lid olish» orders the queue by.")
    bill: bool = Field(description="A plan bill is open.")
    facebook: bool = Field(description="Facebook is tied.")
    page: bool = Field(description="A page is chosen.")
    business: bool = Field(description="The business is filled in.")
    returned: bool = Field(description="Signed in again after signing up.")


class LeadKindOut(BaseModel):
    value: str
    label: str


class CardOut(BaseModel):
    id: str
    board: str
    column: str = Field(description="The column's code.")
    client: ClientOut
    manager: PersonOut | None
    contact_mark: str = Field(description="`contacted`, `no_contact` or empty.")
    attempts: int = Field(
        description="Sales: how many times «Bog'lanilmadi» was pressed."
    )
    needs_support: bool = Field(
        description="«Support kerak»: a ticket opens when the client pays."
    )
    reasons: list[str] = Field(
        description="Support: why the ticket is open, as codes, for chips."
    )
    reason_chips: list[ReasonChipOut] = Field(
        description="The same reasons with their words, to draw the chips from."
    )
    due_at: datetime | None = Field(
        description="The deadline set on the card; count the timer down to it."
    )
    overdue: bool = Field(description="The deadline has passed.")
    offer: CardOfferOut | None = Field(
        description="Sales: the client's discount: their Start payment's, or "
        "the one a manager's «Gaplashildi» started."
    )
    kind: LeadKindOut | None = Field(
        None,
        description="Sales: the kind of lead the client is now (`start_live`, "
        "`start_ended`, `start_expired`, `new`), what «Lid olish» sorts by.",
    )
    taken_as: LeadKindOut | None = Field(
        None,
        description="Sales: how the card came to its manager: the kind it was "
        "when taken, or `phone` (taken by the client's number). Null until "
        "somebody took it, and for cards taken before this was kept.",
    )
    has_bill: bool = Field(
        description="Sales: the client opened a plan bill and may still pay it."
    )
    heat: CardHeatOut | None = Field(
        None,
        description="Sales, an open card: how warm the lead is, from what the "
        "client did after signing up.",
    )
    client_denied: bool = Field(
        False, description="Support: the client said «Yo'q», it is not solved."
    )
    client_replied: bool = Field(
        False, description="Support: the client wrote back while it waited."
    )
    unreachable_reason: str = Field(
        "",
        description="Support, «Bog'lanib bo'lmadi»: the reason's words; empty elsewhere.",
    )
    confirm_until: datetime | None = Field(
        None,
        description="Support, Tasdiq kutilmoqda: unanswered by then, the "
        "ticket closes on its own.",
    )
    renewal: CardRenewalOut | None = Field(
        None, description="Uzaytirish only: the term and the client's figures."
    )
    opened_at: datetime
    column_since: datetime
    closed_at: datetime | None


class BoardColumnOut(ColumnOut):
    total: int = Field(
        description="Cards in the column for this person, with the search."
    )
    recent_days: int | None = Field(
        None,
        description="Support's Hal qilindi and Yopildi: only cards that came "
        "there this many days back are counted and listed (a search reads all).",
    )
    cards: list[CardOut]


class DueCountsOut(BaseModel):
    overdue: int
    today: int = Field(description="Due on the office's day today, passed or not.")


class TakeKindOut(BaseModel):
    value: str = Field(
        description="`start_live`, `start_ended`, `start_expired` or `new`."
    )
    label: str
    count: int
    own: bool = Field(description="One of the reader's kinds.")


class TakeOut(BaseModel):
    queue: int = Field(
        description="Support: tickets in Yangi with nobody on them. Sotuv: "
        "leads in Ishlanmagan with nobody on them."
    )
    own: int = Field(
        description="Of `queue`, the ones of the reader's kinds (an open reason "
        "of a kind set for them in the Support or Sotuv settings). Equals "
        "`queue` for somebody who takes every kind. «Zayavka olish» "
        "gives these first, then any."
    )
    working: int = Field(
        description="Support: the reader's tickets in Ishlanmoqda. Sotuv: the "
        "leads the reader took that still stand in Yangi lead, not called."
    )
    limit: int = Field(
        description="«Zayavka olish» / «Lid olish» is refused once `working` "
        "reaches this."
    )
    kinds: list[TakeKindOut] | None = Field(
        None,
        description="Sotuv: the waiting leads by kind, in the order «Lid "
        "olish» gives them; `own` marks the reader's kinds. Null on Support.",
    )


class BoardViewOut(BaseModel):
    board: str
    take: TakeOut | None = Field(
        None,
        description="Support: what «Zayavka olish» shows; Sotuv: what «Lid "
        "olish» shows; Uzaytirish: null.",
    )
    due: DueCountsOut = Field(
        description="Deadlines on the board under the same search and filters, "
        "whatever the `due` filter."
    )
    columns: list[BoardColumnOut]


class PlanOut(BaseModel):
    name: str
    status: str
    expires_at: datetime
    expired: bool = Field(False, description="The term is over.")
    setup_done: bool


class ClientTroubleOut(BaseModel):
    kind: str
    label: str
    what: str
    urgent: bool
    since: datetime | None


class ClientDetailOut(ClientOut):
    role: str
    language: str
    last_login: datetime | None
    plan: PlanOut | None
    troubles: list[ClientTroubleOut] = Field(
        default_factory=list,
        description="Support: what is wrong with the account now, worst first.",
    )


class ActionOut(BaseModel):
    value: str = Field(
        description="What `POST /cards/{id}/actions` takes as `action`: a button "
        "of the code (`contacted`, `resolve`, …) or one of the superuser's own (`b_…`)."
    )
    label: str
    is_default_label: bool = Field(
        True,
        description="The button's own words: a screen in another language names it "
        "by `value`. False: the superuser's words, shown as typed.",
    )
    due: str = Field(
        description="`required`: ask for a time and send it as `due_at`; "
        "`optional`: offer the time; empty: none."
    )
    note_required: bool = Field(description="Ask for a line and send it as `note`.")
    reason: str = Field(
        "",
        description="Ask for a reason and send its code as `reason`: `close`, "
        "`decline` or `no_contact` names the list in "
        "`GET /office/boards/{board}/reasons?purpose=`; `unreachable` is "
        "Support's own list (`contact-reasons`, the `id`). Empty: none asked.",
    )


class BillOut(BaseModel):
    number: str
    plan: str
    amount_minor: int
    currency: str
    status: str = Field(description="`pending` or `held`.")
    expires_at: datetime


class HistoryOut(BaseModel):
    kind: str
    label: str
    from_column: str
    to_column: str
    from_name: str = Field(
        "",
        description="The column's name when it is the superuser's own (also one "
        "taken off the board since); empty for the columns the board came with.",
    )
    to_name: str = Field("", description="As `from_name`.")
    actor: PersonOut | None = Field(description="Empty when a rule did it.")
    body: str
    at: datetime


class ReasonTargetOut(BaseModel):
    kind: str = Field(description="`launch` or `action`.")
    id: str
    name: str = Field(description="The campaign's name, or the change's.")


class TicketReasonOut(BaseModel):
    code: str = Field(
        description="`setup`, `from_sales`, `meta_error`, `survey`, `idle`, "
        "`ai` (sent from the assistant's chat) or `manual` (opened in the office)."
    )
    label: str
    detail: str = Field(description="What happened, in plain words.")
    at: datetime
    state: str = Field("open", description="`open`, or `solved` by a «Hal qilindi».")
    solved_at: datetime | None = None
    solved_by: str = ""
    solved_note: str = Field("", description="How it was solved, as staff wrote.")
    denied_at: datetime | None = Field(
        None, description="The client said it was not solved: open again."
    )
    raw: str = Field("", description="The provider's own words, to quote.")
    target: ReasonTargetOut | None = Field(
        None, description="What the fact was about: a launch or a change."
    )


class ResolutionOut(BaseModel):
    note: str
    by: str
    at: datetime | None
    client: str = Field(
        description="`waiting`: asked, no answer yet; `yes`: confirmed; "
        "`silent`: did not answer in time."
    )
    count: int = Field(description="Reasons this «Hal qilindi» solved.")


class ClientProfileOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    language: str | None = None
    is_blocked: bool
    joined_at: datetime | None = None
    last_login_at: datetime | None = None


class ClientBusinessOut(BaseModel):
    name: str
    direction: str
    city: str | None = None


class ClientTermOut(BaseModel):
    plan: str
    status: str
    status_label: str
    started_at: datetime | None = None
    expires_at: datetime | None = None
    days_left: int | None = Field(
        default=None, description="Empty once the term has ended."
    )


class ClientMetaOut(BaseModel):
    status: str
    status_label: str
    name: str | None = None
    action_required: bool


class ClientPageOut(BaseModel):
    name: str | None = None
    is_active: bool
    live_groups: int = Field(description="Adverts running on this page now.")
    instagrams: list[str]


class ClientBillOut(BaseModel):
    number: str | None = None
    kind: str = Field(
        "", description="`plan`, `pages`, `seats`...: `kind_label` as a code."
    )
    kind_label: str
    status: str
    status_label: str
    plan: str
    amount_minor: int
    currency: str
    period_days: int | None = None
    created_at: datetime
    paid_at: datetime | None = None


class CardClientOut(BaseModel):
    """The client behind a card, to read only: for whoever sees the card."""

    profile: ClientProfileOut
    businesses: list[ClientBusinessOut]
    subscription: ClientTermOut | None = None
    meta: ClientMetaOut | None = None
    pages: list[ClientPageOut]
    telegram: bool = Field(description="The client's Telegram bot is linked.")
    bills: list[ClientBillOut] = Field(description="The newest ten.")


class CardDetailOut(CardOut):
    client: ClientDetailOut
    bill: BillOut | None = Field(
        description="Sales: the plan bill the client opened and may still pay."
    )
    ticket_reasons: list[TicketReasonOut] = Field(description="Support: newest first.")
    resolution: ResolutionOut | None = Field(
        None, description="Support: a ticket called solved, and the client's word."
    )
    support_chat_id: str | None = Field(
        description="The client's Yordam chat, to open it from the ticket."
    )
    close_reason: str
    close_reason_label: str
    close_note: str
    actions: list[ActionOut] = Field(description="The buttons to show, in order.")
    history: list[HistoryOut] = Field(description="Newest first.")
    calls: list[CallOut] = Field(
        description="Phone calls with the client's number, newest first; the "
        "same on the client's Sales and Support cards."
    )


class ActionIn(BaseModel):
    action: str = Field(
        description="One of the card's `actions`. Sales: `contacted`, "
        "`no_contact`, `callback`, `will_pay`, `offer`, `needs_support`, `close`, "
        "`release`. Support: `start`, `wait`, `unreachable`, `to_developer`, "
        "`resolve`, `release`, `reopen`. "
        "Uzaytirish: `contacted`, `no_contact`, `callback`, `will_pay`, `decline`."
    )
    due_at: datetime | None = Field(
        None,
        description="The deadline, with its zone. Required where the action's "
        "`due` is `required`; ignored where it is empty.",
    )
    on: bool = Field(
        True, description="`needs_support` only: false takes the mark off."
    )
    reason: str = Field(
        "",
        max_length=36,
        description="`close`: a code from `GET /office/boards/sales/reasons`. "
        "`decline`: one from `GET /office/boards/renewal/reasons`. "
        "`no_contact`: one from `GET /office/boards/{board}/reasons?purpose=no_contact`, "
        "required while the action's `reason` says so. "
        "`unreachable`: an `id` from `GET /office/boards/support/contact-reasons`.",
    )
    note: str = Field(
        "",
        max_length=2000,
        description="Required with a reason whose `note_required` is true and where the action's "
        "`note_required` is true.",
    )


class DueIn(BaseModel):
    due_at: datetime | None = Field(
        description="The new deadline, with its zone; null takes it off."
    )
    note: str = Field("", max_length=2000)


class CardAddIn(BaseModel):
    user_id: str = Field(
        description="A client from `GET /office/boards/{board}/clients`."
    )
    note: str = Field(
        "", max_length=2000, description="Support: required, why the ticket is opened."
    )
    staff_id: str | None = Field(
        None,
        description="The manager to give the lead to at once; on Support, the "
        "member the ticket goes to. Only who gives cards out may send it.",
    )


class ClientCardOut(BaseModel):
    id: str
    column: str
    closed: bool


class ClientFoundOut(ClientOut):
    card: ClientCardOut | None = Field(
        description="The card this client already has on the board."
    )


class ClientsFoundOut(BaseModel):
    clients: list[ClientFoundOut]


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    staff_id: str | None = Field(description="Empty: back to Ishlanmagan.")


class ContactReasonOut(BaseModel):
    id: str
    name: str
    position: int
    is_archived: bool


class ContactReasonsOut(BaseModel):
    rows: list[ContactReasonOut] = Field(
        description="Archived ones only for who may edit the list."
    )
    may_edit: bool = Field(description="The Owner and the superuser keep the list.")


class ContactReasonIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    position: int = Field(0, ge=0, le=1000)


class ReasonOut(BaseModel):
    value: str
    label: str
    note_required: bool = Field(
        False, description="Picked with a line written: send it as `note`."
    )


class ReasonRowOut(BaseModel):
    id: str
    code: str = Field(description="What a card keeps; never changes.")
    name: str
    position: int
    note_required: bool
    is_archived: bool
    is_default: bool = Field(description="One the board came with.")


class ReasonListOut(BaseModel):
    purpose: str = Field(description="`close`, `decline`, `no_contact` or `move`.")
    label: str
    hint: str = Field(description="When the list is asked, in a line.")
    rows: list[ReasonRowOut] = Field(description="In order, archived ones too.")


class ReasonListsOut(BaseModel):
    board: str
    may_edit: bool = Field(description="The superuser: adds, renames, archives.")
    lists: list[ReasonListOut]


class ReasonAddIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    note_required: bool = False


class ReasonEditIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=0, le=10_000)
    note_required: bool = False


class StaffListOut(BaseModel):
    staff: list[PersonOut]


class HelpOptionOut(BaseModel):
    index: int
    text: str
    help: bool = Field(description="Choosing it opens a Support ticket.")


class HelpOptionsOut(BaseModel):
    question_id: str
    survey_id: str
    kind: str = Field(description="Only `choice` questions take marks.")
    options: list[HelpOptionOut]


class HelpOptionsIn(BaseModel):
    options: list[int] = Field(
        max_length=10,
        description="Every option that asks for a specialist; the rest lose the mark.",
    )


class ColumnEditIn(BaseModel):
    code: str = Field(max_length=24)
    name: str = Field(min_length=1, max_length=40)


class ButtonOut(BaseModel):
    id: str
    code: str
    action: str = Field(
        description="A button of the code, or `go`: the superuser's own."
    )
    is_custom: bool
    label: str
    is_default_label: bool
    default_label: str
    to_column: str = Field(description="The superuser's column; empty: `default_to`.")
    default_to: str = Field(
        description="Where the button's own rule puts the card; empty: it stays."
    )
    movable: bool = Field(description="Whether `to_column` may be set.")
    rule_note: str = Field(
        description="A word on a button that goes where its rule says."
    )
    to_missing: bool = Field(description="Its column was taken off the board.")
    due: str
    note_required: bool
    position: int
    is_default: bool


class ButtonColumnOut(BaseModel):
    code: str
    name: str
    is_custom: bool
    configurable: bool = Field(
        description="False: a queue or a column that closes a card; `fixed` names its buttons."
    )
    marks_only: bool = Field(
        description="A discount column: buttons leave a mark, the card stays."
    )
    is_changed: bool = Field(description="Differs from what the code gives it.")
    buttons: list[ButtonOut]
    fixed: list[str]


class ButtonCatalogOut(BaseModel):
    action: str
    label: str
    due: str
    note_required: bool
    movable: bool
    default_to: str
    rule_note: str


class ButtonTargetOut(BaseModel):
    code: str
    name: str


class ButtonsOut(BaseModel):
    board: str
    may_edit: bool = Field(description="The superuser.")
    max_per_column: int
    columns: list[ButtonColumnOut]
    catalog: list[ButtonCatalogOut] = Field(
        description="The buttons a column may be given; `go` is the superuser's own."
    )
    targets: list[ButtonTargetOut] = Field(
        description="The columns a button may send a card to."
    )


class ButtonAddIn(BaseModel):
    column: str = Field(max_length=24)
    action: str = Field(max_length=24, description="From `catalog`.")
    label: str = Field("", max_length=40, description="Required for `go`.")
    to_column: str = Field("", max_length=24, description="Required for `go`.")
    due: str = Field("", max_length=16, description="`go`: ``, `optional`, `required`.")
    note_required: bool = False


class ButtonEditIn(BaseModel):
    label: str = Field("", max_length=40)
    to_column: str = Field("", max_length=24)
    due: str = Field("", max_length=16)
    note_required: bool = False
    position: int = Field(ge=0, le=10_000)


class ButtonResetIn(BaseModel):
    column: str = Field(max_length=24)


class ColumnAddIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    after: str | None = Field(
        None,
        max_length=24,
        description="The visible column's code it stands right after. Empty: "
        "before the first final column.",
    )


class ColumnsIn(BaseModel):
    columns: list[ColumnEditIn] = Field(
        max_length=20,
        description="Every visible column of the board, in the new order, with its name.",
    )


class MoveIn(BaseModel):
    column: str = Field(
        max_length=24, description="A visible column's code on the card's board."
    )
    reason: str = Field(
        "",
        max_length=2000,
        description="Why, in the mover's words. Required while the board's "
        "`move` list is empty, and with a listed reason whose `note_required` is true.",
    )
    reason_code: str = Field(
        "",
        max_length=24,
        description="A code from `GET /office/boards/{board}/reasons?purpose=move`; "
        "required once that list has a reason.",
    )
    contact_reason: str = Field(
        default="",
        max_length=64,
        description="Into Support's «Bog'lanib bo'lmadi»: the reason's id from "
        "the Owner's list (required there, ignored elsewhere).",
    )


class StaffRoleOut(BaseModel):
    value: str
    label: str


class StaffPersonOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    is_staff: bool
    is_superuser: bool
    roles: list[StaffRoleOut]


class StaffPeopleOut(BaseModel):
    people: list[StaffPersonOut]


class StaffAddIn(BaseModel):
    user_id: str
    roles: list[str] = Field(
        max_length=7, description="Role values, e.g. `Sales`, `SalesLead`, `Support`."
    )


class StaffRolesIn(BaseModel):
    roles: list[str] = Field(
        max_length=7, description="The whole set; what is left out is taken away."
    )


class TicketQuestionOut(BaseModel):
    asked_at: datetime = Field(description="When Support called the ticket solved.")
    expires_at: datetime = Field(
        description="Unanswered by then, the ticket is closed on its own."
    )


class TicketQuestionStateOut(BaseModel):
    question: TicketQuestionOut | None = Field(
        description="«Muammoyingiz hal bo'ldimi?» waits for the client; null: "
        "nothing to ask."
    )


class TicketAnswerIn(BaseModel):
    solved: bool = Field(description="true: «Ha»; false: «Yo'q», reopen it.")


class TicketAnswerOut(BaseModel):
    result: str = Field(
        description="`solved`, `reopened`, or `stale`: the question was "
        "answered already or is no longer asked."
    )


class RenewalManagerOut(BaseModel):
    manager: PersonOut | None = Field(
        description="Who every new renewal card goes to; null: nobody."
    )
    moved: int = Field(0, description="Open cards that passed to the new manager.")


class RenewalManagerIn(BaseModel):
    staff_id: str | None = Field(
        description="A renewal manager from `GET /office/boards/renewal/staff`; "
        "null: new cards go to nobody."
    )


class ReportReasonOut(BaseModel):
    code: str
    label: str
    count: int


class ReportLineOut(BaseModel):
    code: str = Field(description="The plan's code; empty on the total.")
    name: str
    due: int = Field(description="Terms that came due in the period.")
    renewed: int
    declined: int
    open: int = Field(description="Still worked.")
    rate: int = Field(description="`renewed` of `due`, in percent.")
    paid: list[RenewalMoneyOut] = Field(description="What the renewals brought.")
    reasons: list[ReportReasonOut] = Field(description="Why clients declined.")


class RenewalReportOut(BaseModel):
    date_from: date
    date_to: date
    total: ReportLineOut
    plans: list[ReportLineOut] = Field(description="Standart, then Pro.")


class SupportKindOut(BaseModel):
    value: str = Field(
        description="`setup`, `from_sales`, `meta_error`, `survey`, `idle`, `ai` "
        "or `manual`."
    )
    label: str


class SupportMemberKindsOut(BaseModel):
    id: str
    name: str
    email: str
    kinds: list[str] = Field(description="The kinds this member takes first.")
    all: bool = Field(
        description="Nothing set: every kind, a kind added later too (the default)."
    )


class SupportKindsOut(BaseModel):
    kinds: list[SupportKindOut] = Field(description="Every kind, in order.")
    members: list[SupportMemberKindsOut] = Field(
        description="Each active member of Support."
    )


class SupportKindsIn(BaseModel):
    kinds: list[str] = Field(
        min_length=1,
        max_length=20,
        description="The kinds this member takes first; at least one. Every kind "
        "ticked is saved as `all`.",
    )


class SalesKindsOut(BaseModel):
    kinds: list[LeadKindOut] = Field(
        description="Every kind of lead, in the order «Lid olish» gives them."
    )
    members: list[SupportMemberKindsOut] = Field(
        description="Each Sales manager with the kinds they take first."
    )


class SalesKindsIn(BaseModel):
    kinds: list[str] = Field(
        min_length=1,
        max_length=10,
        description="The kinds of lead this manager takes first; at least one. "
        "Every kind ticked is saved as `all`.",
    )


class PhoneTakeIn(BaseModel):
    phone: str = Field(
        min_length=1,
        max_length=32,
        description="The client's number, written any way: +998 90 123-45-67, "
        "or at least its last nine digits.",
    )


class SupportReportLineOut(BaseModel):
    talked: int = Field(
        description="Different clients the member wrote to in the support chat, "
        "or on whose ticket they wrote a note, pressed «Mijoz kutilmoqda», "
        "«Dasturchiga berish» or «Hal qilindi». Calls are not counted yet."
    )
    messages: int = Field(description="Messages the member wrote in support chats.")
    taken: int = Field(description="Tickets taken with «Zayavka olish».")
    solved: int = Field(description="«Hal qilindi» presses.")
    confirmed: int = Field(
        description="The client said solved, after this member's «Hal qilindi»."
    )
    denied: int = Field(
        description="The client said not solved, after this member's «Hal qilindi»."
    )


class SupportReportDayOut(SupportReportLineOut):
    day: date = Field(description="The office's day (Tashkent).")


class SupportReportMemberOut(BaseModel):
    id: str
    name: str
    email: str
    total: SupportReportLineOut = Field(
        description="The period; `talked` counts each client once."
    )
    days: list[SupportReportDayOut] = Field(
        description="Days with anything done, newest first."
    )


class SupportReportOut(BaseModel):
    date_from: date
    date_to: date
    total: SupportReportLineOut = Field(
        description="Everybody listed; `talked` counts each client once."
    )
    members: list[SupportReportMemberOut] = Field(
        description="A member of Support reads their own line only; the Owner and "
        "the superuser read every member of Support, and anybody else who worked "
        "tickets in the period."
    )


class SalesFiguresOut(BaseModel):
    leads: int = Field(
        description="Cards opened: sign-ups that became leads. Only in the "
        "lead's view; 0 on a staff row."
    )
    taken: int = Field(description="«Lid olish» pressed, or a card given by the lead.")
    contacted: int = Field(description="«Gaplashildi» pressed.")
    no_contact: int = Field(description="«Bog'lanib bo'lmadi» pressed.")
    callbacks: int = Field(description="«Vaqt qo'yish» pressed.")
    sold: int = Field(description="First full plan paid; Start is not a sale.")
    sold_offer: int = Field(description="Of `sold`: with the 20%/10% discount on.")
    closed: int = Field(description="Closed by a person or by the discount ending.")
    rate: int = Field(
        description="`sold` of `leads` in percent on the total and a day in the "
        "lead's view; of `taken` on a staff row and in a manager's own view."
    )
    calls: int = Field(description="The office exchange's calls by the person.")
    calls_answered: int
    talk_seconds: int
    money: list[RenewalMoneyOut] = Field(description="The sales' first bills.")
    first_touch_minutes: int | None = Field(
        description="Median minutes from «Lid olish» to the first call button; "
        "null: none in the period."
    )


class SalesDayOut(SalesFiguresOut):
    day: date


class SalesKindLineOut(BaseModel):
    value: str = Field(
        description="`start_live`, `start_ended`, `start_expired`, `new`, `phone` "
        "(taken by the "
        "client's number), or empty: taken before the kind was kept."
    )
    label: str
    taken: int = Field(description="Cards taken (or given) in the period.")
    sold: int = Field(description="Sales in the period on such cards.")
    rate: int = Field(description="`sold` of `taken`, in percent.")
    money: list[RenewalMoneyOut] = Field(description="The sales' first bills.")


class SalesStaffOut(SalesFiguresOut):
    staff: PersonOut | None = Field(
        description="null: «Menejersiz» - clients who paid with nobody on them."
    )
    open_now: int = Field(description="Open cards in the person's hand now.")
    overdue_now: int = Field(description="Of `open_now`: past their time now.")
    reasons: list[ReportReasonOut] = Field(description="Why their cards closed.")
    kinds: list[SalesKindLineOut] = Field(
        default_factory=list, description="Their figures by kind of lead."
    )


class SalesQueueOut(BaseModel):
    waiting: int = Field(description="Leads in Ishlanmagan with nobody on them now.")
    oldest_at: datetime | None


class SalesSourceOut(BaseModel):
    code: str = Field(description="`email`, `google`, `telegram`; empty: not known.")
    label: str
    leads: int = Field(description="The period's leads that signed up so.")
    sold: int = Field(description="Of them, sold by now.")
    rate: int


class SalesCampaignOut(BaseModel):
    source: str
    campaign: str
    leads: int
    sold: int
    rate: int


class SalesReportOut(BaseModel):
    date_from: date
    date_to: date
    scope: str = Field(description="`all`: everybody's; `own`: the reader's only.")
    total: SalesFiguresOut
    queue: SalesQueueOut | None = Field(description="The lead's view only.")
    days: list[SalesDayOut] = Field(
        description="Every day of the period, oldest first."
    )
    staff: list[SalesStaffOut] = Field(
        description="Every Sales person (most sold first), and «Menejersiz» last."
    )
    reasons: list[ReportReasonOut] = Field(description="Why the period's cards closed.")
    kinds: list[SalesKindLineOut] = Field(
        default_factory=list,
        description="Taken and sold by kind of lead: every kind and «Raqam bilan "
        "olingan» always, «Oldin olingan» only when there are such.",
    )
    sources: list[SalesSourceOut] = Field(
        description="The lead's view only: the period's leads by how they signed up."
    )
    campaigns: list[SalesCampaignOut] = Field(
        description="The lead's view only: the period's leads by utm_source and "
        "utm_campaign, most first (at most 15); leads with no marks left out."
    )
