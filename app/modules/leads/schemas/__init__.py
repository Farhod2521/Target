"""Response shapes for the leads screens, for the API reference only.

The routes keep returning plain dicts; these are attached with ``responses=``
so Redoc shows each body without the route validating or trimming it.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.ads.selectors.labels import AdLabel
from app.modules.crm.selectors import LeadPlace
from app.modules.leads.selectors.core import LeadFilters
from app.modules.leads.selectors.reads import LeadCounts
from app.modules.metrics.selectors.lead_sources import LeadSources
from core.leads.questions import Answer


class Choice(BaseModel):
    value: str
    label: str


class LeadOut(BaseModel):
    id: str
    full_name: str
    phone_e164: str
    email: str
    city: str
    provider: str
    form: str = Field(description="Lead form name, empty if unknown.")
    campaign_external_id: str
    adset_external_id: str
    ad_external_id: str
    submitted_at: datetime
    is_test: bool
    is_organic: bool
    anonymized_at: datetime | None
    verdict: str | None = Field(
        description="`qualified`, `unqualified`, or null while unmarked."
    )
    note: str = Field(description="`Sinov`, `Reklamasiz`, or empty.")
    source: AdLabel | None = Field(description="The advert the lead came from.")
    place: LeadPlace | None = Field(
        description="Where the lead sits on the CRM board; null when CRM is off."
    )
    is_new: bool = Field(description="Arrived after the `after` cursor.")


class LeadDetailOut(LeadOut):
    answer_rows: list[Answer] = Field(description="Every form question and its answer.")
    statuses: list[Choice]


class LeadPageOut(BaseModel):
    number: int
    pages: int
    total: int
    first: int = Field(description="1-based index of the first row on this page.")
    last: int


class TroubleOut(BaseModel):
    untracked: int
    failed: int
    recoverable: int = Field(
        description="How many `POST /leads/recover` can fetch again."
    )
    unrecoverable: int
    total: int = Field(description="untracked + failed")


class LeadListOut(BaseModel):
    rows: list[LeadOut]
    crm_on: bool
    page: LeadPageOut
    counts: LeadCounts
    trouble: TroubleOut
    newest_at: datetime | None
    filters: LeadFilters = Field(description="The filters as applied, after cleaning.")
    source: AdLabel | None = Field(description="The advert named by `ad`, if any.")
    adset_name: str
    statuses: list[Choice]
    unmarked: str = Field(description="The `verdict` value that means not marked yet.")
    cursor: str = Field(description="Send back as `since` to `GET /leads/stream`.")
    seconds: int = Field(description="How often to poll `GET /leads/stream`.")
    live: bool = Field(description="True on page 1, the only page worth polling.")
    after: str = Field(
        default="",
        description="Only on `GET /leads`: send back as `after` so new rows get `is_new`.",
    )


class LeadSourcesOut(BaseModel):
    report: LeadSources
    days: int = Field(description="The period applied; 0 means all time.")
    periods: list[int]
    all_time: int


class RecoverOut(BaseModel):
    queued: int
    detail: str


__all__ = [
    "LeadDetailOut",
    "LeadListOut",
    "LeadOut",
    "LeadSourcesOut",
    "RecoverOut",
]
