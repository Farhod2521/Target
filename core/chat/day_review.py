"""The shape Claude answers the daily report in.

Pydantic, like every wire format the API enforces as a tool signature. It
may say something about each campaign it was shown and nothing about one it
was not: ``index`` points into the report's own list, and a note whose
index is not on that list is dropped by the caller.
"""

from typing import Final, Literal

from pydantic import BaseModel, Field

# How many campaigns one day's report may carry. The same ceiling the
# selector cuts the list at.
MAX_DAY_CAMPAIGNS: Final = 8

Verdict = Literal["good", "watch", "bad"]


class CampaignNote(BaseModel):
    """One campaign's day, judged in a word and explained in a line."""

    index: int = Field(
        description="The campaign's number in the report's own list.",
        ge=0,
        le=MAX_DAY_CAMPAIGNS - 1,
    )
    verdict: Verdict = Field(
        description=(
            "good - results at or below their usual cost; watch - too early "
            "to tell or slightly dearer; bad - money going with nothing, or "
            "clearly dearer than usual."
        )
    )
    line: str = Field(
        description=(
            "One short sentence in the reader's language saying why. No "
            "figure that is not in the report."
        ),
        max_length=180,
    )


class DayReview(BaseModel):
    """The reading of one whole finished day."""

    summary: str = Field(
        description=(
            "One or two sentences in the reader's language: how the day went "
            "overall. No greeting, no figure that is not in the report."
        ),
        max_length=400,
    )
    notes: list[CampaignNote] = Field(
        description="At most one note per campaign in the report.",
        default_factory=list,
        max_length=MAX_DAY_CAMPAIGNS,
    )
    advice: str = Field(
        description=(
            "The one thing worth doing today, in one sentence, or an empty "
            "string when nothing needs doing."
        ),
        default="",
        max_length=220,
    )


__all__ = ["MAX_DAY_CAMPAIGNS", "CampaignNote", "DayReview", "Verdict"]
