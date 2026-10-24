"""The shape Claude answers the weekly report in."""

from pydantic import BaseModel, Field


class WeekReview(BaseModel):
    """The reading of one completed week."""

    summary: str = Field(
        description=(
            "One or two sentences in the reader's language: how the week went "
            "against the week before, and what it lines up with when the "
            "report's list of changes or a campaign's diagnosis says so. No "
            "greeting, no figure that is not in the report."
        ),
        max_length=400,
    )
    advice: str = Field(
        description=(
            "The one thing worth doing this week, in one sentence, or an "
            "empty string when nothing needs doing."
        ),
        default="",
        max_length=220,
    )


__all__ = ["WeekReview"]
