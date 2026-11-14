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
    columns: bool = Field(description="Renames and reorders columns.")
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


class ColumnsOut(BaseModel):
    board: str
    live_since: datetime | None = Field(
        description="Sign-ups and events before it are not on the board."
    )
    columns: list[ColumnOut]


class ClientOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    signed_up_at: datetime


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
        None, description="When `next_percent` ends: the card closes then."
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
        description="Sales: the discount given, if «Chegirma berish» was pressed."
    )
    has_bill: bool = Field(
        description="Sales: the client opened a plan bill and may still pay it."
    )
    client_denied: bool = Field(
        False, description="Support: the client said «Yo'q», it is not solved."
    )
    client_replied: bool = Field(
        False, description="Support: the client wrote back while it waited."
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
    cards: list[CardOut]


class DueCountsOut(BaseModel):
    overdue: int
    today: int = Field(description="Due on the office's day today, passed or not.")


class TakeOut(BaseModel):
    queue: int = Field(description="Tickets in Yangi with nobody on them.")
    working: int = Field(description="The reader's tickets in Ishlanmoqda.")
    limit: int = Field(
        description="«Zayavka olish» is refused once `working` reaches this."
    )


class BoardViewOut(BaseModel):
    board: str
    take: TakeOut | None = Field(
        None, description="Support only: what «Zayavka olish» shows."
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
    value: str
    label: str
    due: str = Field(
        description="`required`: ask for a time and send it as `due_at`; "
        "`optional`: offer the time; empty: none."
    )
    note_required: bool = Field(description="Ask for a line and send it as `note`.")


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
        "`release`. Support: `start`, `wait`, `resolve`, `release`, `reopen`. "
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
        max_length=24,
        description="`close`: a code from `GET /office/boards/sales/reasons`. "
        "`decline`: one from `GET /office/boards/renewal/reasons`.",
    )
    note: str = Field(
        "",
        max_length=2000,
        description="Required for `close` and `decline` with `other` and where the action's "
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


class ReasonOut(BaseModel):
    value: str
    label: str


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


class ColumnsIn(BaseModel):
    columns: list[ColumnEditIn] = Field(
        max_length=20,
        description="Every visible column of the board, in the new order, with its name.",
    )


class MoveIn(BaseModel):
    column: str = Field(
        max_length=24, description="A visible column's code on the card's board."
    )
    reason: str = Field(min_length=1, max_length=2000)


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
