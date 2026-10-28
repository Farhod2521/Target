"""Response shapes for the marketing site's data, for the API reference only.

Attached with ``responses=``: the routes still return plain dicts.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.billing.schemas import DisplayOut, PlanOut


class TestimonialOut(BaseModel):
    id: str
    kind: str
    image: str
    video: str
    audio: str
    text: str


class TestimonialCard(TestimonialOut):
    is_copy: bool = Field(description="A repeat, added so the loop has enough cards.")


class CardOut(BaseModel):
    icon: str
    title: str
    body: str


class TagOut(BaseModel):
    label: str | None
    value: str


class QuestionOut(BaseModel):
    question: str
    answer: str


class HomeOut(BaseModel):
    dial_code: str = Field(description="e.g. `+998`.")
    phone_example: str
    testimonials: list[TestimonialOut]
    testimonial_cards: list[TestimonialCard] = Field(description="The carousel's loop.")
    testimonial_loop_seconds: int
    problems: list[CardOut]
    steps: list[CardOut]
    features: list[CardOut]
    targeting_sample: list[TagOut]
    plans: list[PlanOut]
    featured_plan: PlanOut | None
    payments_on: bool
    display: DisplayOut = Field(description="Which currency to show prices in.")
    entry_plan: PlanOut | None = Field(description="The cheapest monthly plan.")
    tier_includes: list[str]
    questions: list[QuestionOut]


class ConsultOut(BaseModel):
    sent: bool
    id: str
    pixel_event: str = Field(description="Fire this Meta Pixel event.")


class DeletionPageOut(BaseModel):
    deletion_sla_days: int


class DeletionCreatedOut(BaseModel):
    confirmation_code: str
    url: str = Field(description="The status page for this request.")


class DeletionStatusOut(BaseModel):
    code: str
    status: str = Field(
        description="`received`, `in_progress`, `completed` or `rejected`."
    )
    is_open: bool
    created_at: datetime
    resolved_at: datetime | None
    deletion_sla_days: int


class PrivacyOut(BaseModel):
    deletion_sla_days: int
    updated_at: date


class TermsOut(BaseModel):
    updated_at: date


class BusinessRef(BaseModel):
    id: str
    name: str


class BusinessPrivacyOut(BaseModel):
    business: BusinessRef
    deletion_sla_days: int
    updated_at: date


__all__ = [
    "BusinessPrivacyOut",
    "ConsultOut",
    "DeletionCreatedOut",
    "DeletionPageOut",
    "DeletionStatusOut",
    "HomeOut",
    "PrivacyOut",
    "TermsOut",
]
