"""The shape and bounds of every look-up's arguments."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_DAYS: Final = 90
DEFAULT_DAYS: Final = 30

LeadGrouping = Literal["day", "campaign", "ad_group", "form", "page"]
CampaignState = Literal["all", "running", "stopped"]
ProposalState = Literal["open", "answered", "all"]
ChangeAction = Literal["budget", "pause", "resume"]
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
            "resume: switch it back on."
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


__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "AdLookup",
    "AdSetLookup",
    "Arguments",
    "CampaignList",
    "CampaignLookup",
    "ChangeAction",
    "ChangeLevel",
    "ChangeProposal",
    "DailyFigures",
    "FormList",
    "LeadCounts",
    "Nothing",
    "Proposals",
    "Search",
    "Window",
]
