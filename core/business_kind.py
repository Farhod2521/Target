"""What kind of business a page belongs to, as a model answers it."""

from pydantic import BaseModel, ConfigDict, Field


class KindGuess(BaseModel):
    """A guess at a business's kind from what its page says about itself."""

    model_config = ConfigDict(extra="forbid")

    direction: str = Field(
        default="",
        max_length=64,
        description="One key from the list of kinds, or empty when unclear.",
    )
    subtype: str = Field(
        default="",
        max_length=80,
        description="The narrower kind, two or three plain Uzbek words, or empty.",
    )
    name: str = Field(
        default="",
        max_length=255,
        description="The business's name as a customer would say it.",
    )
    about: str = Field(
        default="",
        max_length=600,
        description="One short Uzbek sentence saying what the business does, or empty.",
    )


__all__ = ["KindGuess"]
