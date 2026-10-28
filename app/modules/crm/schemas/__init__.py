"""Response shapes for the CRM board and its settings, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.ads.selectors.labels import AdLabel
from app.modules.crm.selectors import AdOption, BoardFilters
from core.leads.questions import Answer


class Choice(BaseModel):
    value: str
    label: str


class CrmUserOut(BaseModel):
    id: str
    full_name: str
    email: str


class StageOut(BaseModel):
    id: str
    name: str
    color: str
    kind: str = Field(description="`new`, `open`, `won` or `lost`.")
    position: int
    counts_as_quality: bool


class CardLeadOut(BaseModel):
    id: str
    full_name: str
    phone_e164: str
    email: str
    city: str
    ad_external_id: str
    ad_title: str = Field(description="Empty outside the board and column lists.")
    submitted_at: datetime


class CardOut(BaseModel):
    id: str
    stage_id: str
    assignee: CrmUserOut | None
    due_at: datetime | None
    due_note: str
    attempts: int = Field(description="Calls marked as not answered.")
    last_note: str
    last_note_at: datetime | None
    returned: int = Field(description="Times the lead came back as a repeat.")
    qualified_at: datetime | None
    won_amount_minor: int | None = Field(description="Sale amount in minor units.")
    currency: str
    lost_reason_name: str
    closed_at: datetime | None
    taken_at: datetime | None
    created_at: datetime
    lead: CardLeadOut


class MemberOut(BaseModel):
    id: str
    user: CrmUserOut | None
    is_active: bool
    seated: bool = Field(
        description="In a seat: their page's free one or a bought one. A manager "
        "out of a seat is locked out and handed no leads."
    )
    takes_leads: bool
    must_change_password: bool
    kpi_fix_minor: int | None
    kpi_percent: int | None
    kpi_currency: str


class ColumnOut(BaseModel):
    stage: StageOut
    cards: list[CardOut]
    total: int = Field(description="Cards in the column, shown or not.")
    won_minor: int = Field(description="Sum of sales in a `won` column.")
    reasons: list[tuple[str, int]] = Field(
        description="`[reason, count]` pairs in a `lost` column."
    )
    start: int
    hidden: int = Field(description="Cards still to load below.")
    next_start: int = Field(
        description="Pass as `start` to `GET /crm/columns/{id}` for the next 40."
    )


class PairOut(BaseModel):
    key: str = Field(description="`page id:ad account id`; send as `pair`.")
    page: str
    account: str


class PairsOut(BaseModel):
    pair: str | None = Field(
        description="The pair this CRM is for; null when the owner has no pair."
    )
    pairs: list[PairOut] = Field(
        description="Every pair the owner may switch to; empty for a manager."
    )


class NavOut(BaseModel):
    url: str = Field(
        description="`/app/crm/` when the CRM is open, else `/app/leads/`."
    )
    attention: int = Field(description="Cards that need the viewer now.")


class BoardOut(PairsOut):
    no_pair: bool = Field(
        False, description="True when the owner has no page and ad account pair yet."
    )
    setup_needed: bool = Field(
        description="True for an owner who has not finished setup; then only `step` "
        "comes with it."
    )
    step: int | None = Field(None, description="Only when `setup_needed`.")
    running: bool | None = None
    is_owner: bool | None = None
    columns: list[ColumnOut] | None = None
    late: int | None = Field(None, description="Cards whose due time has passed.")
    today: int | None = Field(None, description="Cards due today.")
    cursor: str | None = Field(None, description="Send to `GET /crm/pulse`.")
    filters: BoardFilters | None = None
    members: list[MemberOut] | None = None
    ads: list[tuple[str, str]] | None = Field(
        None, description="`[ad id, title]` pairs for the advert filter."
    )


class PulseOut(BaseModel):
    cursor: str
    layout_changed: bool = Field(
        description="Columns changed too; reload `GET /crm` instead of the cards."
    )


class HistoryOut(BaseModel):
    kind: str = Field(
        description="`arrived`, `returned`, `assigned`, `taken`, `moved`, `note`, "
        "`no_answer`, `due_set`, ..."
    )
    text: str
    actor: CrmUserOut | None
    created_at: datetime


class ReasonOut(BaseModel):
    id: str
    name: str


class CardViewOut(BaseModel):
    card: CardOut
    answers: list[Answer] = Field(description="Form answers other than contacts.")
    source: AdLabel | None
    history: list[HistoryOut] = Field(description="Newest first.")
    stages: list[StageOut]
    members: list[MemberOut]
    reasons: list[ReasonOut]
    currency: str
    can_work: bool = Field(description="False once the card is closed.")
    pair: str | None = Field(description="The pair the card is on.")


class SetupOut(BaseModel):
    state: str = Field(description="`draft`, `on` or `off`.")
    step: int
    since: str = Field(description="`new`, `yesterday`, `week`, `month` or `date`.")
    leads_since: datetime | None
    every_ad: bool
    ad_external_ids: list[str]
    offered_ad_ids: list[str]
    take_new_ads: bool
    distribution: str = Field(description="`round_robin`, `claim` or `manual`.")
    currency: str


class PresetOut(BaseModel):
    key: str
    label: str
    kind: str
    color: str
    default: bool = Field(description="Ticked when setup opens.")
    always: bool = Field(description="Cannot be unticked.")


class SettingsOut(PairsOut):
    setup: SetupOut | None
    stages: list[StageOut]
    members: list[MemberOut]
    reasons: list[ReasonOut]
    ads: list[AdOption]
    presets: list[PresetOut]
    colors: list[str]
    custom_slots: int = Field(description="How many custom columns may be added.")
    since_choices: list[Choice]
    distribution_choices: list[Choice]


class SetupStepOut(SettingsOut):
    next: int = Field(description="The next step; 5 means setup is finished.")
    placed: int = Field(
        description="Leads put on the board when the CRM was switched on."
    )


class OkOut(BaseModel):
    ok: bool


class DetailOut(BaseModel):
    detail: str


class PlacedOut(BaseModel):
    placed: int


class CardsMovedOut(BaseModel):
    cards_moved: int


class CardsReleasedOut(BaseModel):
    cards_released: int


__all__ = [
    "BoardOut",
    "CardOut",
    "CardViewOut",
    "CardsMovedOut",
    "CardsReleasedOut",
    "ColumnOut",
    "DetailOut",
    "MemberOut",
    "NavOut",
    "OkOut",
    "PlacedOut",
    "PulseOut",
    "ReasonOut",
    "SettingsOut",
    "SetupStepOut",
    "StageOut",
]
