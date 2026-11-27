"""The shape and bounds of every look-up's arguments."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_DAYS: Final = 90
DEFAULT_DAYS: Final = 30

LeadGrouping = Literal["day", "campaign", "ad_group", "form", "page"]
CampaignState = Literal["all", "running", "stopped"]
ProposalState = Literal["open", "answered", "all"]
ChangeAction = Literal[
    "budget",
    "pause",
    "resume",
    "rename",
    "end_date",
    "no_end_date",
    "cost_cap",
    "audience",
    "placement",
    "advert_text",
]
ChangeGender = Literal["", "all", "men", "women"]
ChangeSwitch = Literal["", "on", "off"]
ChangeApps = Literal["", "auto", "fbig", "instagram", "facebook"]
ChangeLevel = Literal["campaign", "adset", "ad"]


class Arguments(BaseModel):
    """Closed: a key nobody declared is a mistake, not an option."""

    model_config = ConfigDict(extra="forbid")


class Nothing(Arguments):
    """A look-up that needs no arguments."""


class Window(Arguments):
    days: int = Field(
        default=DEFAULT_DAYS,
        ge=1,
        le=MAX_DAYS,
        description="How many days back to read, today included.",
    )


class Search(Arguments):
    query: str = Field(
        min_length=2,
        max_length=100,
        description="A name or part of one, or an id exactly as the person wrote it.",
    )


class CampaignList(Window):
    account_id: str = Field(
        default="",
        max_length=64,
        description=(
            "Only this ad account's campaigns. Empty for every ad account "
            "in the subscription."
        ),
    )
    status: CampaignState = Field(
        default="all", description="Running campaigns, stopped ones, or all."
    )


class CampaignLookup(Window):
    campaign_id: str = Field(min_length=1, max_length=64)


class AdSetLookup(Window):
    adset_id: str = Field(
        min_length=1,
        max_length=64,
        description="The ad group's id, from campaign_details or find.",
    )


class AdLookup(Window):
    ad_id: str = Field(min_length=1, max_length=64)


class DailyFigures(Arguments):
    object_id: str = Field(
        default="",
        max_length=64,
        description=(
            "A campaign, ad group or advert id. Empty for every campaign "
            "of the current ad account together."
        ),
    )
    days: int = Field(default=14, ge=1, le=MAX_DAYS)


class LeadCounts(Window):
    group_by: LeadGrouping = Field(default="campaign")


class FormList(Arguments):
    page_id: str = Field(
        default="",
        max_length=64,
        description="Only this page's forms. Empty for every page.",
    )


class Proposals(Arguments):
    which: ProposalState = Field(
        default="all",
        description="Waiting for an answer, already answered, or all.",
    )


class ChangeProposal(Arguments):
    """One change the owner asked for, prepared for them to confirm. Nothing is carried out."""

    action: ChangeAction = Field(
        description=(
            "budget: set a new daily budget. pause: switch it off. "
            "resume: switch it back on. rename: a new name (any level). "
            "end_date: the last day it runs (adset). no_end_date: take the "
            "end date off (adset). cost_cap: the most one result may cost, "
            "0 removes it (adset). audience: age, gender, Advantage+ audience "
            "(adset). placement: where it is shown (adset). advert_text: an "
            "advert's text, headline, description, button word or site "
            "address (ad)."
        ),
    )
    level: ChangeLevel = Field(
        description=(
            "What the id is: a campaign, an ad group (adset) or an advert (ad). "
            "A daily budget lives on the campaign or on its ad groups - "
            "campaign_details says which carries it."
        ),
    )
    object_id: str = Field(
        min_length=1,
        max_length=64,
        description="The id from a look-up's result. Never a name.",
    )
    daily_budget: str = Field(
        default="",
        max_length=20,
        pattern=r"^(\d{1,9}([.,]\d{1,2})?)?$",
        description=(
            "For a budget only: the new daily budget in the ad account's own "
            "currency, a plain number such as 15 or 12.50. Never a percentage: "
            "work the amount out and say it to the owner first."
        ),
    )
    name: str = Field(
        default="", max_length=100, description="For rename only: the new name."
    )
    end_date: str = Field(
        default="",
        pattern=r"^(\d{4}-\d{2}-\d{2})?$",
        description="For end_date only: the last day, as YYYY-MM-DD.",
    )
    cost_cap: str = Field(
        default="",
        max_length=20,
        pattern=r"^(\d{1,9}([.,]\d{1,2})?)?$",
        description=(
            "For cost_cap only: the most one result may cost, in the ad "
            "account's currency, a plain number. 0 removes the ceiling."
        ),
    )
    age_min: int | None = Field(
        default=None, ge=18, le=65, description="For audience: the youngest age."
    )
    age_max: int | None = Field(
        default=None,
        ge=18,
        le=65,
        description="For audience: the oldest age; 65 is 65+.",
    )
    gender: ChangeGender = Field(
        default="", description="For audience: all, men or women. Empty keeps it."
    )
    advantage: ChangeSwitch = Field(
        default="",
        description=(
            "For audience: Meta's own widening of the audience (Advantage+ "
            "audience), on or off. Empty keeps it."
        ),
    )
    apps: ChangeApps = Field(
        default="",
        description=(
            "For placement only: auto (Meta chooses), fbig (Facebook and "
            "Instagram), instagram or facebook."
        ),
    )
    message: str | None = Field(
        default=None, max_length=2000, description="For advert_text: the main text."
    )
    headline: str | None = Field(
        default=None, max_length=255, description="For advert_text: the headline."
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="For advert_text: the line under the headline.",
    )
    button: str = Field(
        default="",
        max_length=40,
        description=(
            "For advert_text: the button's word as Meta names it, e.g. "
            "LEARN_MORE, SHOP_NOW, SIGN_UP. Only one the advert may carry."
        ),
    )
    link: str = Field(
        default="",
        max_length=1000,
        description="For advert_text: another site address for the advert to open.",
    )


__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "AdLookup",
    "AdSetLookup",
    "Arguments",
    "CampaignList",
    "CampaignLookup",
    "ChangeAction",
    "ChangeApps",
    "ChangeGender",
    "ChangeLevel",
    "ChangeProposal",
    "ChangeSwitch",
    "DailyFigures",
    "FormList",
    "LeadCounts",
    "Nothing",
    "Proposals",
    "Search",
    "Window",
]
