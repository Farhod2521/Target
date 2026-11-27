"""What a model answers when it reads one message of the advert chat."""

from pydantic import BaseModel, ConfigDict, Field


class HeardOut(BaseModel):
    """The form filled from one message. Empty: the message did not say it."""

    model_config = ConfigDict(extra="forbid")

    offer: str = Field(default="", max_length=500)
    goal: str = Field(default="", max_length=64)
    link: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=32)
    channel: str = Field(default="", max_length=32)
    budget: str = Field(default="", max_length=32)
    budget_currency: str = Field(default="", max_length=8)
    start_day: str = Field(default="", max_length=16)
    kind: str = Field(default="", max_length=300)
    kind_direction: str = Field(default="", max_length=64)
    kind_subtype: str = Field(default="", max_length=80)
    sold_name: str = Field(default="", max_length=80)
    sold_price: str = Field(default="", max_length=60)
    understood: bool = True


__all__ = ["HeardOut"]
