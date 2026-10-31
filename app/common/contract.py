"""The shapes the cabinet reads as it is: camelCase keys and money as integers.

The cabinet was written against its own contract before this backend
existed, and translated each answer in the browser (``packages/api/src/live``
in the frontend). A route that answers in these shapes needs no translation
there: the browser reads it as it is. Fields are written here in snake_case
like everything else and leave as camelCase.
"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.common.money import provider_money


class Camel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True
    )


class Money(Camel):
    """An amount as the cabinet draws it: integer minor units and their exponent."""

    minor: int
    currency: str
    exponent: int = Field(description="Digits after the separator: 2 for USD and UZS.")


class RefusalFix(Camel):
    """The one button of a refusal: an address, or a screen of the wizard."""

    label: str
    url: str | None = None
    to: str | None = None


class Refusal(Camel):
    """A refusal from the network, the same wherever it happened."""

    key: str | None = Field(
        None, description="Ask `GET /refusals/answer` with it while `explaining`."
    )
    retryable: bool = Field(False, description="It passes by itself: wait and retry.")
    title: str
    cause: str
    steps: list[str] = Field(default_factory=list)
    provider_words: str | None = Field(
        None, description="What the network wrote for the advertiser."
    )
    html: str | None = Field(
        None, description="The written answer; shown instead of `cause` and `steps`."
    )
    explaining: bool = Field(False, description="That answer is being written.")
    fix: RefusalFix | None = None
    retry_after_seconds: int | None = None


class RefusalAnswer(Camel):
    key: str
    html: str | None = None
    explaining: bool = False


def money(minor: int | None, currency: str, *, provider: str = "meta") -> Money | None:
    """``None`` stays ``None``: an amount nobody knows is not a zero."""
    if minor is None:
        return None
    return Money(
        minor=int(minor),
        currency=currency,
        exponent=provider_money(provider=provider).decimal_places(currency),
    )


def zero_or(minor: int | None, currency: str, *, provider: str = "meta") -> Money:
    """An amount the cabinet always draws: zero when there is none."""
    found = money(minor or 0, currency, provider=provider)
    assert found is not None
    return found


__all__ = [
    "Camel",
    "Money",
    "Refusal",
    "RefusalAnswer",
    "RefusalFix",
    "money",
    "zero_or",
]
