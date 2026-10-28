"""Response shapes for the numbers screens, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.metrics.selectors.campaign_panel import CampaignPanel
from app.modules.metrics.selectors.creative_report import CreativeReport
from app.modules.metrics.selectors.dashboard import Dashboard
from app.modules.metrics.selectors.panel import AdChips, ChipRow
from app.modules.onboarding.schemas import SetupOut


class Choice(BaseModel):
    value: str
    label: str


class RangeOut(BaseModel):
    key: str = Field(description="`today`, `7`, `30`, `90`, or `custom`.")
    since: date
    until: date
    days: int
    is_custom: bool
    earliest: date = Field(description="The first day a custom range may start on.")


class PageSummary(BaseModel):
    name: str
    key: str
    currency: str


class AccountOut(BaseModel):
    id: str
    name: str
    currency: str
    timezone: str


class NumbersOut(BaseModel):
    crm_qualified: int | None = Field(
        description="Qualified leads counted by the CRM; null when the CRM is off."
    )
    dashboard: Dashboard
    filters: RangeOut = Field(description="The range applied.")
    periods: list[Choice]
    page: PageSummary
    ad_account: AccountOut | None
    synced_at: datetime | None
    behind_since: datetime | None = Field(description="Figures stopped arriving at.")
    is_stale: bool
    since: str = Field(
        description="Pass to `GET /metrics/numbers/poll` after a refresh."
    )
    syncing: bool
    account_ids: list[str]
    auto_refresh: bool = Field(
        description="Call `POST /metrics/numbers/refresh?on_open=true`."
    )
    tries: int
    poll_seconds: int
    gave_up: bool = Field(False, description="Only on the poll.")
    message: str = Field("", description="Only on a refresh the owner pressed.")
    setup: SetupOut | None = Field(
        None,
        description="Only on `GET /metrics/numbers`: how far preparation has got. "
        "The dashboard draws the preparation card while `setup.ready` is false.",
    )


class CardOut(BaseModel):
    key: str
    label: str
    hint: str
    is_on: bool = Field(description="Chosen to show on the dashboard.")
    is_on_row: bool
    is_daily: bool
    is_per_goal: bool


class CardGroupOut(BaseModel):
    key: str
    label: str
    cards: list[CardOut]


class CardsOut(BaseModel):
    groups: list[CardGroupOut]
    chosen_count: int


class CardsSavedOut(BaseModel):
    message: str
    chosen: list[str]


class CampaignRef(BaseModel):
    id: str
    name: str


class CampaignPanelOut(BaseModel):
    campaign: CampaignRef
    panel: CampaignPanel


class CreativesOut(BaseModel):
    campaign: CampaignRef
    report: CreativeReport
    result_heading: str
    is_alone: bool = Field(description="The campaign has a single advert.")
    has_cards: bool


class CampaignChipsOut(BaseModel):
    rows: list[ChipRow] = Field(description="One row per campaign.")
    spend_total_minor: int | None
    spend_currency: str


class AdChipsOut(BaseModel):
    rows: list[AdChips] = Field(description="One row per advert.")
    groups: list[ChipRow] = Field(description="One row per ad set.")


class TodayOut(BaseModel):
    tries: int | None = Field(description="Ask again with this; null means stop.")
    poll_seconds: int
    landed: bool = Field(description="Today's figures arrived: reload the figures.")


__all__ = [
    "AdChipsOut",
    "CampaignChipsOut",
    "CampaignPanelOut",
    "CardsOut",
    "CardsSavedOut",
    "CreativesOut",
    "NumbersOut",
    "TodayOut",
]
