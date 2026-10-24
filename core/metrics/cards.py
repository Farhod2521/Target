"""Which figures a campaign panel may show, and what each one is."""

from dataclasses import dataclass
from typing import Final, Literal

CardKey = Literal[
    "spend",
    "cpl",
    "cpql",
    "cpm",
    "cpc",
    "platform_cpl",
    "leads",
    "qualified",
    "quality_share",
    "leads_reported",
    "impressions",
    "reach",
    "frequency",
    "ctr",
    "link_ctr",
    "clicks",
    "link_clicks",
    "unique_clicks",
    "video_plays",
    "video_thruplays",
    "video_hold",
]

CardGroup = Literal["money", "result", "delivery", "engagement", "video"]

Basis = Literal["period", "day"]

Unit = Literal["money", "count", "percent", "ratio"]

GROUPS: Final[tuple[CardGroup, ...]] = (
    "money",
    "result",
    "delivery",
    "engagement",
    "video",
)


@dataclass(frozen=True, slots=True)
class CardSpec:
    """One figure the panel can draw."""

    key: CardKey
    group: CardGroup
    basis: Basis
    unit: Unit
    lower_is_better: bool = False
    is_default: bool = False


CARDS: Final[tuple[CardSpec, ...]] = (
    CardSpec(
        key="cpl",
        group="money",
        basis="period",
        unit="money",
        lower_is_better=True,
        is_default=True,
    ),
    CardSpec(
        key="spend",
        group="money",
        basis="period",
        unit="money",
        is_default=True,
    ),
    CardSpec(
        key="cpm", group="money", basis="period", unit="money", lower_is_better=True
    ),
    CardSpec(
        key="cpc", group="money", basis="period", unit="money", lower_is_better=True
    ),
    CardSpec(
        key="platform_cpl",
        group="money",
        basis="period",
        unit="money",
        lower_is_better=True,
    ),
    CardSpec(
        key="leads",
        group="result",
        basis="period",
        unit="count",
        is_default=True,
    ),
    CardSpec(key="leads_reported", group="result", basis="period", unit="count"),
    CardSpec(
        key="impressions",
        group="delivery",
        basis="period",
        unit="count",
        is_default=True,
    ),
    CardSpec(key="reach", group="delivery", basis="day", unit="count", is_default=True),
    CardSpec(
        key="frequency",
        group="delivery",
        basis="day",
        unit="ratio",
        lower_is_better=True,
    ),
    CardSpec(
        key="ctr",
        group="engagement",
        basis="period",
        unit="percent",
        is_default=True,
    ),
    CardSpec(
        key="link_ctr",
        group="engagement",
        basis="period",
        unit="percent",
    ),
    CardSpec(key="clicks", group="engagement", basis="period", unit="count"),
    CardSpec(key="link_clicks", group="engagement", basis="period", unit="count"),
    CardSpec(key="unique_clicks", group="engagement", basis="day", unit="count"),
    CardSpec(key="video_plays", group="video", basis="period", unit="count"),
    CardSpec(key="video_thruplays", group="video", basis="period", unit="count"),
    CardSpec(key="video_hold", group="video", basis="period", unit="percent"),
)

BY_KEY: Final[dict[str, CardSpec]] = {card.key: card for card in CARDS}

DEFAULT_KEYS: Final[tuple[CardKey, ...]] = tuple(
    card.key for card in CARDS if card.is_default
)

ROW_KEYS: Final[tuple[CardKey, ...]] = (
    "spend",
    "leads",
    "cpl",
    "reach",
    "impressions",
)


def chosen_keys(stored: object) -> tuple[CardKey, ...]:
    """The cards to draw, from whatever the preference row happens to hold."""
    if not isinstance(stored, list):
        return ()
    picked = {item for item in stored if isinstance(item, str)}
    return tuple(card.key for card in CARDS if card.key in picked)


def stored_or_default(stored: object) -> tuple[CardKey, ...]:
    """What to draw for an account that may never have chosen."""
    return DEFAULT_KEYS if stored is None else chosen_keys(stored)


def specs_for(keys: tuple[CardKey, ...]) -> tuple[CardSpec, ...]:
    """The catalogue entries behind a choice, in the order given."""
    return tuple(BY_KEY[key] for key in keys)


__all__ = [
    "BY_KEY",
    "CARDS",
    "DEFAULT_KEYS",
    "GROUPS",
    "ROW_KEYS",
    "Basis",
    "CardGroup",
    "CardKey",
    "CardSpec",
    "Unit",
    "chosen_keys",
    "specs_for",
    "stored_or_default",
]
