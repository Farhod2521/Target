"""What the review screen's save takes, section by section.

A field left out of a section keeps what the launch holds; ``null`` clears a
field that may be empty, and a field that may not be empty refuses it.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.ads.constants import LAUNCH_NAME_MAX, MAX_GEO_ADDRESS
from app.modules.ads.inputs.ending import EndingIn
from app.modules.ads.inputs.questions import QuestionRow
from core.targeting import MAX_AGE, MAX_RADIUS_KM, MIN_AGE, MIN_RADIUS_KM

Role = Literal["include", "exclude"]


class PlacePick(BaseModel):
    """A row of the place search, as it was offered."""

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)


class AudienceIn(BaseModel):
    targeting_mode: str = ""
    placement_mode: str = ""
    lead_buying: str = ""
    age_min: int = Field(MIN_AGE, ge=MIN_AGE, le=MAX_AGE)
    age_max: int = Field(MAX_AGE, ge=MIN_AGE, le=MAX_AGE)
    genders: list[Literal[1, 2]] = Field(
        default_factory=list, description="Empty: everyone."
    )
    geo_mode: str = ""
    places: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list, description="Place names typed in.")
    picked: list[PlacePick] = Field(
        default_factory=list, description="Rows chosen from the place search."
    )
    areas: list[str] = Field(default_factory=list)
    radius_km: int | None = Field(None, ge=MIN_RADIUS_KM, le=MAX_RADIUS_KM)
    lat: Decimal | None = Field(None, ge=-90, le=90)
    lng: Decimal | None = Field(None, ge=-180, le=180)
    address: str = Field("", max_length=MAX_GEO_ADDRESS)
    audiences: dict[str, Role] = Field(default_factory=dict)


class InterestsIn(BaseModel):
    queries: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)


class CreativeIn(BaseModel):
    position: int = Field(ge=0)
    primary_text: str = ""
    headline: str | None = Field("", max_length=60)
    description: str | None = Field("", max_length=120)
    ad_name: str | None = Field(
        "", max_length=LAUNCH_NAME_MAX, description="Null: the generated name."
    )


class FormSectionIn(BaseModel):
    lead_form: str | None = Field(
        "", max_length=128, description="Null or empty: a new form of ours."
    )
    rows: list[QuestionRow] | None = None
    ending: EndingIn | None = None
    form_depth: str = ""
    higher_intent: bool | None = None


class AdvancedIn(BaseModel):
    campaign_type: str = ""
    conversion_event: str = ""
    pixel_id: str = ""
    call_to_action: str = ""
    url_tags: str | None = ""
    end_date: date | None = None
    attribution: str | None = ""
    cap_times: int | None = Field(None, ge=1, le=50)
    cap_days: int | None = Field(None, ge=1, le=90)
    max_result_cost: Decimal | None = Field(None, ge=0, description="Null: no cap.")


class ProposalIn(BaseModel):
    audience: AudienceIn | None = None
    interests: InterestsIn | None = None
    traits: list[str] | None = Field(None, description="The trait queries kept.")
    creatives: list[CreativeIn] | None = Field(
        None, description="Only the adverts sent; the others are left as they are."
    )
    form: FormSectionIn | None = None
    advanced: AdvancedIn | None = None
