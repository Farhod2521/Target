"""The shape Claude answers the weekly report in.

Pydantic, like every wire format the API enforces as a tool signature. Two
fields and no per-campaign notes: the week's message already judges each
campaign by the product's own rules, and what it lacks without a model is
the reading of the week as a whole and the one thing to do next.
"""

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
