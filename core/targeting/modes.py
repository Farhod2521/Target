"""What each of the three audience modes does to a spec.

One subject, kept out of :mod:`core.targeting.validators` because it is one:
that module corrects a spec against limits, and this one decides how much of
the audience decision the advertiser is keeping. The two meet in one place -
:func:`fit`, which the validator calls near the end - and everything a mode
implies is written here so no screen and no builder has to work it out again.

Its twin one question along is :mod:`core.targeting.placements`: that one
decides where the ad appears, is written after this, and shares nothing
with it but the shape.

**The provider vocabulary is here rather than in an adapter, and that is the
documented asymmetry of this package.** ``core/targeting`` produces a spec
in the provider's own shape - ``geo_locations``, ``flexible_spec``,
``age_min`` - because the spec is what gets sent, and inventing an
``AudienceIntent`` from one provider would shape it exactly like that
provider. ``targeting_automation`` joins that list. What does *not* cross is
the other way round: the domain says "automatic" and only this file knows
which key and which number that is.

Three findings from the v26.0 guides sit behind the constants below, and
each is a place a guess would have cost a refused launch or a silently
wider audience:

* **The switch has to be sent either way.** *"Beginning with v23.0, the
  ``advantage_audience`` parameter within ``targeting_automation`` defaults
  to 1 or requires an explicit value of either 1 or 0."* Omitting it no
  longer means "off" - it means the provider chooses, and it chooses on.
  That is why :func:`automation` has no empty case.
* **What automation will not expand is a published list**, and it is short:
  *"Non-negotiable business constraints are NOT expanded, these include
  location constraints, minimum age, language, and custom audience
  exclusions."* Everything else given - interests, behaviours, gender, and
  an included custom audience - is a suggestion the provider may deliver
  beyond. A suggestion is still where delivery starts, so interests are not
  sent in this mode at all: a wrong one spends the learning budget on the
  wrong people first.
* **Age stops being a range and becomes a floor.** *"advertisers can pass
  ``age_min`` values ranging between 18 to 25 only"* and *"advertisers
  cannot set ``age_max`` values. ``age_max`` is fixed at 65."* Both are
  refused rather than ignored, so the mode has to correct them before the
  spec goes anywhere.

No Django, no clock, no configuration.
"""

from typing import Any, Final, Literal, get_args

from core.targeting.adjustments import Adjustment

# How much of the audience decision the advertiser is keeping.
#
# Three, and they are exclusive rather than a set of flags. The provider
# expresses this as two independent things - whether a detailed-targeting
# block is present, and a separate automation switch - and modelling it
# that way would put four states on a screen, two of which cannot be
# described in a sentence: "these interests, but the platform may ignore
# them" needs two controls and a paragraph, while the three below need one
# control and one line each.
#
#   automatic  - the provider decides, with no detailed targeting given.
#                What is given becomes a suggestion it may deliver beyond,
#                except the handful of things it treats as non-negotiable -
#                see the quotes at the top of this module. The default
#   interests  - the audience the advertiser approved is the audience. The
#                only mode where a confirmed interest is required
#   broad      - no detailed targeting at all: where, how old, which
#                gender, and nothing else. For a catalogue that keeps losing
#                interest categories underneath it, and for anybody who
#                wants the interests off without handing over the decision
#
# Not the provider's words. Meta brands the first "Advantage+ audience"
# and Google calls its own "optimized targeting"; naming the *decision*
# rather than either brand is what keeps a picker from being one platform's
# marketing on a screen. The same bargain ``AudienceBreadth`` makes.
TargetingMode = Literal["automatic", "interests", "broad"]

# The provider's own default, and this product's.
#
# The twin of ``DEFAULT_PLACEMENT_MODE``: omitting the switch has meant
# "the provider chooses, and it chooses on" since v23.0, so ``interests``
# is no neutral answer either - it is an explicit ``advantage_audience: 0``
# on every campaign, decided by nobody.
#
# Not the value that changes nothing, and that is the point rather than a
# side effect: a launch in this mode sends no interests and lets the
# provider find the audience from its own signals.
DEFAULT_TARGETING_MODE: Final[TargetingMode] = "automatic"


# The three, in the order a picker shows them: the recommended one first,
# the same order ``PLACEMENT_MODES`` takes and for the same reason - a
# screen that buries the provider's own recommendation under the opt-out is
# arguing with the platform without saying so.
#
# Derived from the type rather than written out again, so a value added to
# one and forgotten in the other cannot happen.
MODES: Final[tuple[TargetingMode, ...]] = get_args(TargetingMode)

# The provider's key for the switch, and its two values. Integers, not
# booleans: the provider reads ``true`` as a string on a form post and
# answers with a refusal naming the field rather than the type.
AUTOMATION_KEY: Final = "targeting_automation"
AUTOMATION_FIELD: Final = "advantage_audience"
AUTOMATION_ON: Final = 1
AUTOMATION_OFF: Final = 0

# The highest ``age_min`` the provider accepts while it is choosing the
# audience itself. Above this it refuses the ad set outright.
AUTOMATIC_MAX_AGE_MIN: Final = 25

# The only ``age_max`` that exists in that mode - which is to say, none. The
# field is removed rather than set to 65: sending the value the provider
# fixes it at is still sending a value, and the refusal names the field
# without saying that any value at all is the problem.
AUTOMATIC_AGE_MAX: Final = 65


def wants_interests(mode: TargetingMode) -> bool:
    """Whether a detailed-targeting block belongs in this spec at all.

    Only ``interests``. Under ``automatic`` the provider would take them as
    a suggestion and still deliver to those people first, so one wrong
    interest steers the first spend; the mode exists to leave the audience
    to the provider entirely. Under ``broad`` there is nothing detailed by
    definition.

    Kept apart from :func:`requires_interests` although the two now agree:
    one asks what goes into the spec, the other whether a spec without them
    may launch, and a fourth mode could answer them differently.
    """
    return mode == "interests"


def requires_interests(mode: TargetingMode) -> bool:
    """Whether a launch in this mode may go out with nothing detailed in it.

    Only ``interests``. This is the whole of what separates a broad
    audience somebody chose from one that happened because every interest
    failed confirmation - the two produce an identical spec, and a check
    that read the spec could not tell them apart.
    """
    return mode == "interests"


def automation(mode: TargetingMode) -> dict[str, int]:
    """The switch, spelled the provider's way. Never absent.

    Always a value, in every mode, because absence stopped meaning "off":
    from v23.0 an omitted switch is the provider's own choice and its own
    choice is on. A spec built by this product says what it wants.
    """
    value = AUTOMATION_ON if mode == "automatic" else AUTOMATION_OFF
    return {AUTOMATION_FIELD: value}


def fit(spec: dict[str, Any], notes: list[Adjustment], *, mode: TargetingMode) -> None:
    """Write the switch and correct what the mode will not accept beside it.

    Called after the ordinary limits and after a Special Ad Category has
    had its say. Order matters both ways: a category pins the age at 18-65,
    which is already within what ``automatic`` allows, and the switch has
    to survive the empty-field sweep that follows. Only the placement block
    is written after this one, and the two share nothing.

    Every correction is reported. The advertiser typed an upper age and is
    about to be sent a spec without one, and a number that changes with no
    sentence beside it reads as a bug - which is the same argument the
    radius and the category make, under one shared reason code so a screen
    can say which decision caused it.
    """
    spec[AUTOMATION_KEY] = automation(mode)
    if mode != "automatic":
        return

    if spec.pop("age_max", None) is not None:
        notes.append(
            Adjustment(
                field="age_max",
                reason="automatic_targeting",
                detail=str(AUTOMATIC_AGE_MAX),
            )
        )

    given = spec.get("age_min")
    if isinstance(given, int) and given > AUTOMATIC_MAX_AGE_MIN:
        spec["age_min"] = AUTOMATIC_MAX_AGE_MIN
        notes.append(
            Adjustment(
                field="age_min",
                reason="automatic_targeting",
                detail=f"{given}->{AUTOMATIC_MAX_AGE_MIN}",
            )
        )


def resolve_mode(value: object) -> TargetingMode:
    """A stored mode, or the default for a missing or unknown one.

    The builder's own reading of the answer. A screen describing the spec
    that read it any other way would describe a campaign nobody is buying.
    """
    return value if value in MODES else DEFAULT_TARGETING_MODE


def sent_ages(
    age_min: int | None, age_max: int | None, *, mode: TargetingMode
) -> tuple[int | None, int | None]:
    """The age range the provider is actually sent under this mode.

    The two corrections :func:`fit` makes to a spec, as numbers rather than
    notes, for a card that has to say what is being bought: under automatic
    targeting there is no upper bound and the lower one is capped.
    """
    if mode != "automatic":
        return age_min, age_max
    low = None if age_min is None else min(age_min, AUTOMATIC_MAX_AGE_MIN)
    return low, None


__all__ = [
    "AUTOMATIC_AGE_MAX",
    "AUTOMATIC_MAX_AGE_MIN",
    "AUTOMATION_FIELD",
    "AUTOMATION_KEY",
    "AUTOMATION_OFF",
    "AUTOMATION_ON",
    "MODES",
    "automation",
    "fit",
    "requires_interests",
    "resolve_mode",
    "sent_ages",
    "wants_interests",
]
