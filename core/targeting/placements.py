"""Where the ad is shown, as one decision instead of thirty-six YAML lines."""

from collections.abc import Mapping
from typing import Any, Final, Literal, get_args

from core.targeting.adjustments import Adjustment

PlacementMode = Literal["automatic", "instagram", "facebook", "standard"]

DEFAULT_PLACEMENT_MODE: Final[PlacementMode] = "automatic"

PLACEMENT_MODES: Final[tuple[PlacementMode, ...]] = get_args(PlacementMode)

PLACEMENT_KEYS: Final[tuple[str, ...]] = (
    "publisher_platforms",
    "facebook_positions",
    "instagram_positions",
    "messenger_positions",
    "audience_network_positions",
    "threads_positions",
    "whatsapp_positions",
    "device_platforms",
)

STANDARD_PLACEMENTS: Final[Mapping[str, tuple[str, ...]]] = {
    "publisher_platforms": ("facebook", "instagram"),
    "facebook_positions": ("feed",),
    "instagram_positions": ("stream", "story", "reels"),
}

INSTAGRAM_ONLY_PLACEMENTS: Final[Mapping[str, tuple[str, ...]]] = {
    "publisher_platforms": ("instagram",),
    "instagram_positions": ("stream", "story", "reels"),
}
FACEBOOK_ONLY_PLACEMENTS: Final[Mapping[str, tuple[str, ...]]] = {
    "publisher_platforms": ("facebook",),
    "facebook_positions": ("feed", "story", "facebook_reels"),
}

_BLOCKS: Final[Mapping[str, Mapping[str, tuple[str, ...]]]] = {
    "standard": STANDARD_PLACEMENTS,
    "instagram": INSTAGRAM_ONLY_PLACEMENTS,
    "facebook": FACEBOOK_ONLY_PLACEMENTS,
}

INSTAGRAM_PLACEMENTS: Final[Mapping[str, tuple[str, ...]]] = {
    "publisher_platforms": ("instagram",),
    "instagram_positions": (
        "stream",
        "story",
        "reels",
        "profile_feed",
        "ig_search",
        "profile_reels",
    ),
}

RETIRED_POSITIONS: Mapping[str, tuple[str, ...]] = {
    "instagram_positions": ("explore", "explore_home"),
    "messenger_positions": ("story",),
}


def fit(spec: dict[str, Any], notes: list[Adjustment], *, mode: PlacementMode) -> None:
    """Write the whole placement block, or remove it."""
    for key in PLACEMENT_KEYS:
        spec.pop(key, None)
    if mode == "automatic":
        return
    for key, values in _BLOCKS[mode].items():
        spec[key] = list(values)
    strip_retired(spec, notes)


def pin_to_instagram(spec: dict[str, Any], notes: list[Adjustment]) -> None:
    """Write the Instagram-only block over whatever the mode wrote."""
    for key in PLACEMENT_KEYS:
        spec.pop(key, None)
    for key, values in INSTAGRAM_PLACEMENTS.items():
        spec[key] = list(values)
    strip_retired(spec, notes)


_CHAT_APP: Final[Mapping[str, str]] = {
    "messenger": "facebook",
    "instagram": "instagram",
}


def keep_chat_reachable(
    spec: dict[str, Any], notes: list[Adjustment], *, mode: PlacementMode, chat: str
) -> None:
    """Hand a one-app answer back to the provider when the chat is elsewhere."""
    if mode not in ("instagram", "facebook") or _CHAT_APP.get(chat) == mode:
        return
    for key in PLACEMENT_KEYS:
        spec.pop(key, None)
    notes.append(
        Adjustment(
            field="publisher_platforms", reason="unsupported_placement", detail=mode
        )
    )


def strip_retired(spec: dict[str, Any], notes: list[Adjustment]) -> None:
    """Remove positions this API version will not deliver on."""
    for key, retired in RETIRED_POSITIONS.items():
        given = spec.get(key)
        if not isinstance(given, list):
            continue
        kept = [position for position in given if position not in retired]
        if len(kept) != len(given):
            notes.append(
                Adjustment(
                    field=key,
                    reason="unsupported_placement",
                    detail=",".join(str(p) for p in given if p in retired),
                )
            )
        spec[key] = kept


def names_a_placement(targeting: Mapping[str, Any]) -> tuple[str, ...]:
    """Which placement keys this mapping carries, if any."""
    return tuple(key for key in PLACEMENT_KEYS if key in targeting)


__all__ = [
    "DEFAULT_PLACEMENT_MODE",
    "FACEBOOK_ONLY_PLACEMENTS",
    "INSTAGRAM_ONLY_PLACEMENTS",
    "INSTAGRAM_PLACEMENTS",
    "PLACEMENT_KEYS",
    "PLACEMENT_MODES",
    "RETIRED_POSITIONS",
    "STANDARD_PLACEMENTS",
    "PlacementMode",
    "fit",
    "keep_chat_reachable",
    "names_a_placement",
    "pin_to_instagram",
    "strip_retired",
]
