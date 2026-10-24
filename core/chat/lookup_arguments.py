"""The shape and bounds of every look-up's arguments.

Apart from :mod:`core.chat.lookups`, which names the tools, for length. Each
model is closed - a key nobody declared is refused before a look-up runs -
and every window is bounded by what the tables actually hold.
"""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

# The longest window any look-up reads. The provider keeps leads for ninety
# days and the segment rows are kept for ninety, so past this the tables are
# thinner than they look.
MAX_DAYS: Final = 90
DEFAULT_DAYS: Final = 30

LeadGrouping = Literal["day", "campaign", "ad_group", "form", "page"]
CampaignState = Literal["all", "running", "stopped"]
ProposalState = Literal["open", "answered", "all"]


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


__all__ = [
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "AdLookup",
    "AdSetLookup",
    "Arguments",
    "CampaignList",
    "CampaignLookup",
    "DailyFigures",
    "FormList",
    "LeadCounts",
    "Nothing",
    "Proposals",
    "Search",
    "Window",
]
