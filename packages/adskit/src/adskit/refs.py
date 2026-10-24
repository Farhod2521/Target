"""How an object on a provider is named."""

from dataclasses import dataclass
from typing import Final, Literal, NewType

ProviderName = NewType("ProviderName", str)

MinorUnits = NewType("MinorUnits", int)

Level = Literal[
    "account",
    "campaign",
    "adset",
    "ad",
    "creative",
    "form",
    "page",
    "interest",
    "location",
    "audience",
    "pixel",
    "lead",
    "dataset",
]

LeadStage = Literal["qualified", "unqualified", "converted"]

TraitKind = Literal["interest", "behaviour", "life_event"]

BROWSED_TRAITS: Final[frozenset[str]] = frozenset({"behaviour", "life_event"})

GeoKind = Literal["city", "region", "country", "other"]

Delivery = Literal[
    "active",
    "paused",
    "paused_above",
    "pending",
    "rejected",
    "finished",
    "unknown",
]

Ranking = Literal[
    "",
    "above_average",
    "average",
    "below_average_10",
    "below_average_20",
    "below_average_35",
    "unknown",
]

AudienceSource = Literal["pixel", "page", "lead_form"]

AudienceAction = Literal[
    "visited",
    "viewed_item",
    "added_to_cart",
    "purchased",
    "engaged",
    "messaged",
    "opened",
    "submitted",
    "abandoned",
    "visited_not_purchased",
    "added_to_cart_not_purchased",
    "engaged_not_messaged",
]

AudienceBreadth = Literal["closest", "balanced", "broad"]

BreakdownKind = Literal["age_gender", "platform_position", "region"]


@dataclass(frozen=True, slots=True)
class ExternalRef:
    """One object on one provider."""

    provider: ProviderName
    level: Level
    id: str

    def __str__(self) -> str:
        """Compact form for logs and idempotency keys: ``meta:adset:123``."""
        return f"{self.provider}:{self.level}:{self.id}"
