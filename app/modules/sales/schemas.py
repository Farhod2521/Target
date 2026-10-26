"""Response shapes for the office's sales board, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonOut(BaseModel):
    id: str
    name: str
    email: str


class PlanLine(BaseModel):
    plan: str
    status: str
    expires_at: datetime


class SalesCardOut(BaseModel):
    id: str
    client_id: str = Field(description="A user id, or a request (ariza) id.")
    name: str
    phone: str
    is_request: bool = Field(description="A website request, not a signed-up user.")
    group: str = Field(description="`ariza`, `problem`, `new`, `back`, `ending`, ...")
    group_label: str
    stage: str
    outcome: str
    column: str = Field(
        description="`taken`, `no_answer`, `callback`, `thinking`, `using`, "
        "`awaiting`, `lost`; empty once closed."
    )
    attempts: int
    callback_at: datetime | None
    claimed_at: datetime | None
    expires_at: datetime | None = Field(description="When the claim lapses.")
    extended_at: datetime | None
    contacted_at: datetime | None
    closed_at: datetime | None
    manager: PersonOut | None
    reason: str
    invoice: str
    live: PlanLine | None = Field(description="The client's running plan.")


class PooledOut(BaseModel):
    """A client waiting in the pool. Requests carry only the first few fields."""

    client_id: str
    is_request: bool
    name: str
    phone: str
    group: str | None
    group_label: str
    asked_at: datetime | None = None
    last_closed: datetime | None = None
    last_reason: str | None = None
    email: str | None = None
    date_joined: datetime | None = None
    live_expires: datetime | None = None
    live_plan_name: str | None = None
    live_status: str | None = None
    live_started: datetime | None = None
    last_plan_name: str | None = None
    last_ended: datetime | None = None
    has_paid: bool | None = None
    is_referred: bool | None = None
    last_outcome: str | None = None
    is_problem: bool | None = None
    is_asked: bool | None = None
    live_plan_id: str | None = None


class ColumnOut(BaseModel):
    key: str
    label: str
    total: int
    hidden: int
    cards: list[SalesCardOut]


class RuleOut(BaseModel):
    percent: int
    ending_days: int = Field(
        description="Days before expiry a client counts as ending."
    )
    set: bool


class PlanRef(BaseModel):
    id: str
    code: str
    name: str


class SegmentOut(BaseModel):
    id: str
    key: str = Field(description="Use as the `g` chip.")
    plan: PlanRef
    days: int


class WhoOut(BaseModel):
    user: PersonOut
    is_lead: bool = Field(description="Sees every manager's cards.")
    is_owner: bool
    chip: str = Field(description="The `g` applied.")
    manager: str = Field(description="The `m` applied.")
    term: str = Field(description="The `q` applied, after cleaning.")
    rule: RuleOut
    segments: list[SegmentOut]


class ChipOut(BaseModel):
    key: str
    label: str
    count: int


class PoolOut(BaseModel):
    who: WhoOut
    chips: list[ChipOut]
    pool_cards: list[PooledOut]
    pool_total: int
    pool_next: int | None = Field(
        description="Pass as `offset` for more; null at the end."
    )


class BoardOut(PoolOut):
    columns: list[ColumnOut]
    held: int = Field(description="Clients this manager holds now.")
    managers: list[PersonOut] = Field(description="For the `m` filter; leads only.")
    cursor: str = Field(description="Send to `GET /office/sales/pulse`.")
    nothing_found: bool
    stages: dict[str, str]
    outcomes: dict[str, str] = Field(description="Values for `outcome`.")
    hold_terms: dict[str, str] = Field(description="Values for `term`.")


class PlacementOut(BaseModel):
    client_id: str
    placed: SalesCardOut | None
    column: str = Field(description="Where the card sits now; `pool`, or empty.")
    pooled: PooledOut | None
    totals: dict[str, int] = Field(description="Column -> card count.")
    pool_total: int
    held: int


class PulseOut(BaseModel):
    columns: list[ColumnOut]
    cursor: str
    held: int


class ConsultOut(BaseModel):
    id: str
    name: str
    phone: str
    created_at: datetime


class HistoryLine(BaseModel):
    id: str
    kind: str
    label: str
    actor: PersonOut | None
    reason: str
    body: str
    callback_at: datetime | None
    created_at: datetime


class BillOut(BaseModel):
    id: str
    number: str
    plan: str
    amount_minor: int
    currency: str
    paid_at: datetime | None
    source: str
    manager: PersonOut | None


class ClientCardOut(BaseModel):
    subject_id: str
    client: PooledOut | None
    consult: ConsultOut | None
    claim: SalesCardOut | None
    queued_group: str | None
    history: list[HistoryLine]
    bills: list[BillOut]
    paid_count: int
    facebook: str
    facebook_name: str
    telegram: str
    launches: int


class HoldOut(BaseModel):
    id: str
    client_id: str
    name: str
    until: datetime | None
    forever: bool
    set_by: PersonOut | None
    reason: str
    created_at: datetime


class ReasonOut(BaseModel):
    id: str
    label: str
    position: int
    archived_at: datetime | None


class DialogOut(BaseModel):
    mode: str = Field(
        description="`own` (yours), `watch` (a lead looking), `queue` (in the pool) "
        "or `gone` (someone else's)."
    )
    refusal: str = Field(description="Why the last press was refused; empty if not.")
    card: ClientCardOut
    hold: HoldOut | None = Field(description="Only in `watch` mode.")
    reasons: list[ReasonOut]
    outcomes: dict[str, str]
    hold_terms: dict[str, str]
    held: int
    placement: PlacementOut | None = Field(None, description="Only after a press.")


class MovedOut(PlacementOut):
    message: str


class SpanOut(BaseModel):
    month: str = Field(description="`YYYY-MM`.")
    start: datetime
    end: datetime


class MonthOut(BaseModel):
    manager_id: str
    name: str
    claimed: int
    contacted: int
    sold: int
    base_minor: int
    commission_minor: int
    currency: str
    open_now: int
    conversion: Any


class ShareOut(BaseModel):
    id: str
    client: PersonOut | None
    invoice: str
    plan: str
    base_minor: int
    percent: int
    amount_minor: int
    currency: str
    earned_at: datetime


class PastMonth(BaseModel):
    month: str
    claimed: int
    contacted: int
    sold: int
    base_minor: int
    commission_minor: int
    currency: str


class MineOut(BaseModel):
    span: SpanOut
    me: MonthOut
    place: int
    ranked: int
    to_next: int | None
    next_place: int | None
    currency: str
    percent: int
    wallet_minor: int
    held: int
    sales: list[ShareOut]
    months: list[PastMonth]


class RankedOut(MonthOut):
    place: int


class TeamOut(BaseModel):
    span: SpanOut
    podium: list[RankedOut]
    table: list[RankedOut]
    mine: RankedOut
    to_next: int | None
    next_place: int | None
    currency: str
    previous: SpanOut
    last_winner: MonthOut | None


class ShareBar(BaseModel):
    label: str
    count: int
    width: int = Field(description="Bar width, percent of the largest.")


class ReportOut(BaseModel):
    span: SpanOut
    live: bool
    closed: bool
    months: list[str] = Field(description="`YYYY-MM` values for `oy`.")
    rows: list[MonthOut]
    currency: str
    totals: MonthOut
    picked: str | None
    picked_sales: list[ShareOut]
    reasons: list[ShareBar]
    sources: list[ShareBar]


class HoldsOut(BaseModel):
    page: int
    pages: int
    total: int
    rows: list[HoldOut]


class MessageOut(BaseModel):
    message: str


class RuleHistoryLine(BaseModel):
    percent: int
    ending_days: int
    valid_from: datetime
    set_by: PersonOut | None


class SettingsOut(BaseModel):
    who: WhoOut
    rule: dict[str, int]
    may_set_percent: bool
    history: list[RuleHistoryLine]
    reasons: list[ReasonOut]
    segments: list[SegmentOut]


class RuleSavedOut(MessageOut):
    changed: bool


class ReasonSavedOut(MessageOut):
    reason: ReasonOut


class SegmentSavedOut(MessageOut):
    segment: SegmentOut


__all__ = [
    "BoardOut",
    "DialogOut",
    "HoldsOut",
    "MessageOut",
    "MineOut",
    "MovedOut",
    "PlacementOut",
    "PoolOut",
    "PulseOut",
    "ReasonSavedOut",
    "ReportOut",
    "RuleSavedOut",
    "SegmentSavedOut",
    "SettingsOut",
    "TeamOut",
]
