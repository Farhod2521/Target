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

# What an owner may tick. Meta lists more: right_hand_column and instream_video
# hang on the objective, video_feeds on the advert being a video.
OFFERED_POSITIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "instagram": (
        "stream",
        "story",
        "reels",
        "profile_feed",
        "profile_reels",
        "ig_search",
    ),
    "facebook": (
        "feed",
        "story",
        "facebook_reels",
        "marketplace",
        "search",
        "profile_feed",
    ),
}

# A position that cannot run alone, and the ones of which one must run beside it.
POSITION_NEEDS: Final[Mapping[tuple[str, str], tuple[tuple[str, str], ...]]] = {
    ("facebook", "story"): (("facebook", "feed"), ("instagram", "story")),
    ("facebook", "marketplace"): (("facebook", "feed"),),
    ("facebook", "search"): (("facebook", "feed"),),
    ("facebook", "profile_feed"): (("facebook", "feed"),),
    ("instagram", "profile_feed"): (("instagram", "stream"),),
    ("instagram", "profile_reels"): (("instagram", "reels"),),
    ("instagram", "ig_search"): (
        ("instagram", "stream"),
        ("instagram", "story"),
        ("instagram", "reels"),
    ),
}


def platforms_of(mode: str) -> tuple[str, ...]:
    """The apps a mode names positions for; none when the provider decides."""
    block = _BLOCKS.get(mode, {})
    return tuple(app for app in OFFERED_POSITIONS if f"{app}_positions" in block)


def chosen_positions(value: object, *, mode: str) -> dict[str, tuple[str, ...]]:
    """What was saved, for the apps this mode runs on, in the order offered."""
    if not isinstance(value, Mapping):
        return {}
    found: dict[str, tuple[str, ...]] = {}
    for app in platforms_of(mode):
        given = value.get(app) or ()
        kept = tuple(item for item in OFFERED_POSITIONS[app] if item in given)
        if kept:
            found[app] = kept
    return found


def shown_positions(value: object, *, mode: str) -> dict[str, tuple[str, ...]]:
    """Each app's ticks: what was saved, else the mode's block, else the app's own."""
    chosen = chosen_positions(value, mode=mode)
    block = _BLOCKS.get(mode, {})
    return {
        app: chosen.get(app)
        or block.get(f"{app}_positions")
        or _BLOCKS[app][f"{app}_positions"]
        for app in OFFERED_POSITIONS
    }


def lonely_position(value: object, *, mode: str) -> tuple[str, str] | None:
    """The first position whose companion is not running, if any."""
    shown = shown_positions(value, mode=mode)
    running = {(app, item) for app in platforms_of(mode) for item in shown[app]}
    for app in platforms_of(mode):
        for item in shown[app]:
            needs = POSITION_NEEDS.get((app, item))
            if needs and not running.intersection(needs):
                return app, item
    return None


def fit(
    spec: dict[str, Any],
    notes: list[Adjustment],
    *,
    mode: PlacementMode,
    positions: object = None,
) -> None:
    """Write the whole placement block, or remove it."""
    for key in PLACEMENT_KEYS:
        spec.pop(key, None)
    if mode == "automatic":
        return
    for key, values in _BLOCKS[mode].items():
        spec[key] = list(values)
    for app, ticked in chosen_positions(positions, mode=mode).items():
        spec[f"{app}_positions"] = list(ticked)
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
    "OFFERED_POSITIONS",
    "PLACEMENT_KEYS",
    "PLACEMENT_MODES",
    "POSITION_NEEDS",
    "RETIRED_POSITIONS",
    "STANDARD_PLACEMENTS",
    "PlacementMode",
    "chosen_positions",
    "fit",
    "keep_chat_reachable",
    "lonely_position",
    "names_a_placement",
    "pin_to_instagram",
    "platforms_of",
    "shown_positions",
    "strip_retired",
]
