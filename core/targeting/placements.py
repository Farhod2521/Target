"""Where the ad is shown, as one decision instead of thirty-six YAML lines.

The twin of :mod:`core.targeting.modes`, one question along. That module
decides who the ad is shown to; this one decides where it appears. Both are
kept out of :mod:`core.targeting.validators` for the same reason - that
module corrects a spec against limits, and these two make a choice - and
both meet the validator in one place, :func:`fit`.

**The provider vocabulary is here rather than in an adapter**, the same
documented asymmetry ``modes`` carries: the spec is what gets sent, and a
``Placement`` abstraction invented from one provider would be shaped
exactly like that provider. The domain says "standard" or "automatic"; only
this file knows which keys and which words that is.

Five findings from the v26.0 documentation sit behind the constants below.

* **Sending nothing is not "no opinion" - it is Advantage+ placements.**
  *"No action is required to opt in to Advantage+ placement, as it is the
  default setting in the API"*, beside *"Refrain from setting placement
  targeting or placement exclusions"*. So a pinned list of placements is
  no neutral default: it is an opt-out of the provider's own
  recommendation.
* **It is the exact inverse of the trap ``advantage_audience`` sets.**
  There, absence means "the provider decides" and the provider decides on;
  here, absence *is* on. Both read "an absent field is off" and both are
  wrong, in opposite directions - which is why neither is left absent by
  accident in this package.
* **Two positions are gone in v26.0 and they fail differently.**
  ``messenger_positions: story`` is *"silently removed for versioned v26.0
  or later calls"*; Instagram Explore is refused - *"requests that
  explicitly specify Explore return an error"*. Silence is the more
  dangerous of the two, because a campaign keeps running with a placement
  its owner believes is live.
* **The reference page and the changelog disagree.** The v26.0 placement
  reference still lists ``explore``, ``explore_home`` and ``messenger
  story``, and still calls ``story`` the messenger default. The changelog
  removed all three, with dates. The dated page wins, and the contradiction
  is written down rather than resolved - it is not the first time two of
  the provider's own pages have said different things.
* **Which placement works with which destination is not published.** The
  documentation names exactly one pairing (``destination_type: FACEBOOK``)
  and is silent about conversations, calls and lead forms. That is the same
  gap ``targeting_optimization``, ``targeting_relaxation_types``,
  ``attribution_spec`` and the ``MESSAGING_*`` goals have, and the reason
  the automatic mode below is worth having at all: in it the pairing is the
  provider's problem rather than a table this product would have to guess.

No Django, no clock, no configuration.
"""

from collections.abc import Mapping
from typing import Any, Final, Literal, get_args

from core.targeting.adjustments import Adjustment

# Who decides where the ad appears.
#
# One app or the provider's choice, and never positions one by one: that
# is the media-buyer question this product does not ask, and the
# combinations the provider accepts are only half published (Facebook
# ``story`` may not be chosen alone; Audience Network may not be chosen
# alone), so a position picker would produce refusals nobody could predict
# from the screen. An Instagram-only block is known to be accepted - the
# profile goal below sends one.
#
#   automatic  - nothing is sent, which is how the provider is told to
#                choose. More inventory, including apps outside Facebook
#                and Instagram, and a cost per result it optimises itself
#   standard   - Facebook and Instagram, in the places this product knows.
#                The whole answer for somebody who wants their ad in the
#                two apps they know they are on and nowhere else
#   instagram  - Instagram alone: feed, Stories and Reels
#   facebook   - Facebook alone: feed, Stories and Reels
#
# ``standard`` is no longer offered. It stays readable because launches
# made while it was offered still carry it, and they are rebuilt with the
# block they were approved with.
#
# Not the provider's words. Meta brands the first "Advantage+ placements";
# what a person has to decide is which of the apps they know their ad is
# shown in.
PlacementMode = Literal["automatic", "instagram", "facebook", "standard"]

# The provider's own default, and this product's too.
#
# The blindness underneath the choice is real: a lead carries the ad it
# came from and never the placement it was seen in, so cost per lead cannot
# be computed per placement even in principle, and the nightly placement
# figures that could show cost per *reported* lead are read by nothing yet.
# Pinning two apps is not the cautious half of that unmeasurable trade -
# it is an opt-out of the provider's own recommendation, taken on no
# evidence, paid for by every advertiser in inventory they never got to
# compete in, and bought with a quality signal nothing reads either way.
#
# Unlike ``DEFAULT_TARGETING_MODE`` this is **not** the value that changes
# nothing: a launch in this mode reaches further than the standard list,
# which is the point rather than a side effect, and the picker still
# carries the other answer for anybody who wants it.
DEFAULT_PLACEMENT_MODE: Final[PlacementMode] = "automatic"

# Every mode a stored answer may hold, the recommended one first.
#
# ``MODES`` in :mod:`core.targeting.modes` still runs tightest-first, and
# the two orders disagree on purpose. That question has no answer outside
# the account it is asked about - who should choose the audience depends on
# what the provider has had to learn from - while this one has an answer
# the provider publishes, and a picker that buries it is arguing with the
# platform on the advertiser's behalf without saying so.
PLACEMENT_MODES: Final[tuple[PlacementMode, ...]] = get_args(PlacementMode)

# Every key the provider reads a placement out of, as of v26.0 - including
# the three this product has never sent.
#
# The list is exhaustive on purpose rather than limited to what
# :data:`STANDARD_PLACEMENTS` writes, because its job is the automatic mode:
# **one key left behind opts the ad set out of Advantage+ placements as
# surely as all eight would**, and the two most recent additions
# (``threads_positions``, ``whatsapp_positions``) are exactly the kind of
# key that gets added to a provider without this file being edited.
#
# ``device_platforms`` belongs here even though it is not a position. It
# restricts delivery the same way and is offered in the same breath by the
# provider's own guides - the call-ads example pins ``mobile`` - so leaving
# it out would mean an "automatic" spec that still carried a restriction.
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

# The standard list, in one place instead of twelve.
#
# Here rather than in the category files: a provider value repeated in
# twelve data files is a provider value that goes stale in twelve data
# files.
#
# **Targeting words, not reporting words.** An ad set targeted with
# ``instagram_positions: [stream]`` has its figures returned under
# ``instagram|feed``, and Audience Network is targeted as ``classic`` and
# reported as ``an_classic``. The two vocabularies are not translated
# anywhere - see the note in ``metaads.adapter`` - so anything that ever
# matches a stored breakdown row against this table needs a map, and
# finding that out from a rule that silently never matches is expensive.
STANDARD_PLACEMENTS: Final[Mapping[str, tuple[str, ...]]] = {
    "publisher_platforms": ("facebook", "instagram"),
    "facebook_positions": ("feed",),
    "instagram_positions": ("stream", "story", "reels"),
}

# One app each, for an owner who wants their ad in that app and nowhere
# else. Facebook Stories may not be chosen alone; beside the feed it may.
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

# Instagram and nothing else, for the one destination that lives there: an
# advert opening an Instagram profile. Ads Manager offers no other placement
# for it, and a live paused ad set kept exactly this list (probe, 2026-09-28).
# Every Instagram position of v26.0 except the retired Explore two.
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

# Positions the current API version no longer accepts, and what happens if
# one is sent anyway.
#
# ``messenger_positions: story`` - **dropped in silence.** *"The `story`
# value in `messenger_positions` is silently removed for versioned v26.0 or
# later calls and no longer appears in effective placements"*, from v26.0
# and in every version by 27 October 2026.
#
# ``instagram_positions: explore`` and ``explore_home`` - **refused.**
# *"The Instagram Explore Feed placement is no longer available ... requests
# that explicitly specify Explore return an error"*, from 29 July 2026.
# Both spellings are here because the changelog names the placement rather
# than the field value, and the reference page lists the pair together.
#
# ``facebook_positions: video_feeds`` is deliberately **not** here. The
# v26.0 reference lists the value as live with no deprecation note
# anywhere, and an entry that strips a placement the provider accepts is
# not a safety net - it is a screen reporting a change nobody made.
RETIRED_POSITIONS: Mapping[str, tuple[str, ...]] = {
    "instagram_positions": ("explore", "explore_home"),
    "messenger_positions": ("story",),
}


def fit(spec: dict[str, Any], notes: list[Adjustment], *, mode: PlacementMode) -> None:
    """Write the whole placement block, or remove it.

    **Replaces rather than merges**, in both directions. A key this
    function does not write is a key the provider will not see, which is
    the same rule ``AudiencePort.apply`` states for a whole spec: an absent
    value means "delete", never "leave as it was". Anything a preset, a
    stored draft or an older version of this catalogue put in a placement
    key is gone by the time the spec is sent.

    That is the point of the automatic mode and most of the value of the
    standard one. Half a placement block is the failure this exists to end:
    a file naming ``messenger_home`` beside a list that does not include
    Messenger looks deliberate and decides nothing.

    Nothing is reported to the owner either way. An adjustment says "you
    asked for one thing and are getting another", and neither mode does
    that - the standard block is not the advertiser's answer being
    narrowed, and the automatic one is the absence they asked for.
    """
    for key in PLACEMENT_KEYS:
        spec.pop(key, None)
    if mode == "automatic":
        return
    for key, values in _BLOCKS[mode].items():
        spec[key] = list(values)
    strip_retired(spec, notes)


def pin_to_instagram(spec: dict[str, Any], notes: list[Adjustment]) -> None:
    """Write the Instagram-only block over whatever the mode wrote.

    Not a third mode. The owner's answer stays what it was and is carried
    beside the spec; this is the destination overruling it, the way a
    Special Ad Category overrules the audience mode - an advert that opens
    an Instagram profile has nowhere else to be shown.
    """
    for key in PLACEMENT_KEYS:
        spec.pop(key, None)
    for key, values in INSTAGRAM_PLACEMENTS.items():
        spec[key] = list(values)
    strip_retired(spec, notes)


# The app each chat surface lives in. A chat advert pinned to the other app
# would open a conversation nobody can reach from where the ad is shown.
_CHAT_APP: Final[Mapping[str, str]] = {
    "messenger": "facebook",
    "instagram": "instagram",
}


def keep_chat_reachable(
    spec: dict[str, Any], notes: list[Adjustment], *, mode: PlacementMode, chat: str
) -> None:
    """Hand a one-app answer back to the provider when the chat is elsewhere.

    The owner chose one app and the conversation opens in the other. The
    provider's own choice is the answer that keeps both, and the change is
    reported rather than made quietly.
    """
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
    """Remove positions this API version will not deliver on.

    Kept as a separate pass over a block :func:`fit` has just written, which
    reads like belt and braces and is deliberate: the two answer to
    different clocks. The standard list is this product's choice and changes
    when somebody decides to change it; the retired table is the provider's
    and changes on the provider's own schedule, published in a changelog
    that is months ahead of the reference page. Writing the list through
    this filter means a value that dies between one deploy and the next
    stops being sent as soon as the table is edited, and the edit is one
    line.

    It also stays honest about the two failure modes. A refused value costs
    a launch and is found immediately; a silently dropped one costs nothing
    and is never found at all, because the campaign runs and the screen
    still names the placement.
    """
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
    """Which placement keys this mapping carries, if any.

    Used by the catalogue loader to refuse them. A preset may not decide
    where an ad appears, and the reason is written where it is enforced -
    see :func:`core.targeting.loader._check_placements`.
    """
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
