from datetime import datetime

from pydantic import BaseModel, Field


class PersonOut(BaseModel):
    id: str
    name: str
    email: str


class RoleOut(BaseModel):
    value: str
    label: str


class BoardOut(BaseModel):
    code: str = Field(description="`sales` or `support`.")
    label: str
    lead: bool = Field(description="Sees the whole board and gives cards out.")


class CanOut(BaseModel):
    take: bool = Field(description="Has the «Lid olish» button.")
    assign: bool = Field(description="Gives a card to somebody else.")
    move: bool = Field(description="Moves a card to any column.")
    columns: bool = Field(description="Renames and reorders columns.")
    staff: bool = Field(description="Adds staff and gives roles.")


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


class CardOut(BaseModel):
    id: str
    board: str
    column: str = Field(description="The column's code.")
    client: ClientOut
    manager: PersonOut | None
    contact_mark: str = Field(description="`contacted`, `no_contact` or empty.")
    needs_support: bool = Field(
        description="«Support kerak»: a ticket opens when the client pays."
    )
    reasons: list[str] = Field(
        description="Support: why the ticket is open, as codes, for chips."
    )
    opened_at: datetime
    column_since: datetime
    closed_at: datetime | None


class BoardColumnOut(ColumnOut):
    total: int = Field(
        description="Cards in the column for this person, with the search."
    )
    cards: list[CardOut]


class BoardViewOut(BaseModel):
    board: str
    columns: list[BoardColumnOut]


class PlanOut(BaseModel):
    name: str
    status: str
    expires_at: datetime
    setup_done: bool


class ClientDetailOut(ClientOut):
    role: str
    language: str
    last_login: datetime | None
    plan: PlanOut | None


class ActionOut(BaseModel):
    value: str
    label: str


class HistoryOut(BaseModel):
    kind: str
    label: str
    from_column: str
    to_column: str
    actor: PersonOut | None = Field(description="Empty when a rule did it.")
    body: str
    at: datetime


class TicketReasonOut(BaseModel):
    code: str = Field(
        description="`setup`, `from_sales`, `meta_error`, `survey` or `idle`."
    )
    label: str
    detail: str
    at: datetime


class CardDetailOut(CardOut):
    client: ClientDetailOut
    ticket_reasons: list[TicketReasonOut] = Field(description="Support: newest first.")
    support_chat_id: str | None = Field(
        description="The client's Yordam chat, to open it from the ticket."
    )
    close_reason: str
    close_reason_label: str
    close_note: str
    actions: list[ActionOut] = Field(description="The buttons to show, in order.")
    history: list[HistoryOut] = Field(description="Newest first.")


class ActionIn(BaseModel):
    action: str = Field(
        description="Sales: `contacted`, `no_contact`, `needs_support`, `close`. "
        "Support: `start`, `resolve`."
    )
    on: bool = Field(
        True, description="`needs_support` only: false takes the mark off."
    )
    reason: str = Field(
        "",
        max_length=24,
        description="`close` only: a code from `GET /office/boards/sales/reasons`.",
    )
    note: str = Field(
        "", max_length=2000, description="Required for `close` with `other`."
    )


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    staff_id: str | None = Field(description="Empty: back to Ishlanmagan.")


class ReasonOut(BaseModel):
    value: str
    label: str


class StaffListOut(BaseModel):
    staff: list[PersonOut]
