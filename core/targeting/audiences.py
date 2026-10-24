"""Which of the advertiser's own audiences this campaign is aimed at.

The third thing that goes into a spec without being an answer to a wizard
question - geography and the conversion source are the other two - and like
them it arrives as an argument to :func:`~core.targeting.builder.build`.
This package cannot read a table, and an audience is a row somewhere else.

**Two sides, and they are not mirror images of each other.** That asymmetry
is the provider's, not a caution of ours, and both halves of it are
published:

* *"Non-negotiable business constraints are NOT expanded, these include
  location constraints, minimum age, language, and custom audience
  exclusions."*
* *"the system will deliver ads beyond their Custom Audience if it's likely
  to improve performance"*

So an **exclusion holds in every mode**, and an **inclusion is a boundary in
two of the three and a starting point in the third**. Nothing here branches
on the mode - the spec is the same either way - but every screen that shows
this has to say which of the two it is, and that is why the modes are named
where they are rather than inferred from a list of ids.

The provider's vocabulary is here rather than in an adapter, for the reason
written out in :mod:`core.targeting.modes`: this package produces a spec in
the shape it gets sent.

No Django, no clock, no configuration.
"""

from dataclasses import dataclass
from typing import Any, Final

from core.targeting.adjustments import Adjustment

# The provider's two keys. Separate fields rather than one signed list, and
# the older shape - custom audiences nested inside ``exclusions`` - is
# deprecated: *"you can still continue using custom audience exclusions by
# using the excluded_custom_audiences field instead."*
INCLUDE_KEY: Final = "custom_audiences"
EXCLUDE_KEY: Final = "excluded_custom_audiences"

# *"Include up to 500 custom audiences in custom_audiences and 500 custom
# audiences in excluded_custom_audiences."* Far above anything this product
# can produce - the picker lists an advertiser's own audiences and nobody
# has five hundred - so this is a documented limit written down rather than
# a guardrail anybody will meet. It costs one line and stops the number
# being looked up again.
MAX_PER_SIDE: Final = 500

# What an adjustment about a vanished audience names. Neither provider key,
# because a row that was deleted was on one of the two sides and the
# sentence does not depend on which - the same latitude ``age`` and
# ``radius`` already take, where the note names the subject rather than the
# pair of fields it was corrected in.
AUDIENCE_FIELD: Final = "audiences"


@dataclass(frozen=True, slots=True)
class AudienceRef:
    """One audience, as much of it as a spec and a sentence need.

    ``external_id`` is the provider's, because that is what gets sent.
    ``label`` is the name the advertiser gave it, and it is here rather
    than looked up later for the reason every other label in this project
    is carried: whoever renders the review screen must be able to say
    *which* audience without asking a second question.

    ``is_lookalike`` is a fact about what the audience is, answered by the
    side that knows, and it exists for one rule: *"Lookalike Audiences"* are
    listed as **removed** for housing, employment and credit ads. Sending
    one produces a campaign that is created, sits at ``WITH_ISSUES`` and
    never delivers - the worst shape a failure can take, because nothing on
    this side ever hears about it.

    ``is_usable`` is the provider's verdict on the audience itself - too
    small to deliver to, still being counted, held for review. Carried the
    same way ``Interest.is_confirmed`` is, and for the same reason: it is a
    fact the caller learned from the provider, and a package that cannot
    make a request has to be told rather than asked.

    It defaults to true, which is the right direction here: an audience
    nobody has said anything about is one the provider has not objected
    to, and treating silence as a refusal would block every launch made
    before this column was read.
    """

    external_id: str
    label: str = ""
    is_lookalike: bool = False
    is_usable: bool = True


@dataclass(frozen=True, slots=True)
class AudienceChoice:
    """Who to show this to, who never to show it to, and what went missing.

    ``dropped`` carries the names of audiences that were chosen and can no
    longer be used - deleted, or no longer usable at the provider. Names
    rather than ids, because it becomes a sentence: the same bargain
    ``GeoChoice.widened`` makes, and for the same reason. A choice that
    quietly stops being in the spec is a choice the advertiser thinks is
    still there.
    """

    included: tuple[AudienceRef, ...] = ()
    excluded: tuple[AudienceRef, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.included and not self.excluded

    @property
    def lookalikes(self) -> tuple[AudienceRef, ...]:
        """Every lookalike named here, on either side.

        Both sides, deliberately. The provider withdraws the *feature* for
        a Special Ad Category rather than one direction of it, and an
        exclusion that names a lookalike is still an ad set naming one.
        """
        return tuple(
            ref for ref in (*self.included, *self.excluded) if ref.is_lookalike
        )

    @property
    def unusable(self) -> tuple[AudienceRef, ...]:
        """Every audience named here that the provider will not deliver on.

        Both sides again. An exclusion the provider refuses is not a
        harmless one: it is a list of people the advertiser believes are
        being kept away from the ad and who are not.

        **Nothing is dropped over this.** An audience that stops being
        usable makes the launch wait rather than making the campaign
        quietly wider - which is what removing it would do, and the
        difference between the two is somebody's budget spent on people
        they took the trouble to name.
        """
        return tuple(
            ref for ref in (*self.included, *self.excluded) if not ref.is_usable
        )


def fit(
    spec: dict[str, Any], notes: list[Adjustment], *, choice: AudienceChoice
) -> None:
    """Write both sides into the spec, and report what did not survive.

    Called from :func:`~core.targeting.validators.validate_structure`
    alongside the mode, before the empty-field sweep - an empty side is
    left out entirely rather than written as ``[]``, which is an error on
    some provider fields and a no-op on others.

    **An audience named on both sides keeps its exclusion and loses its
    inclusion.** Unreachable from the screen, which offers one three-way
    choice per audience rather than two independent lists, and therefore
    reachable only from a hand-edited form or a draft written by an older
    version of this code. The direction is the safe one: the exclusion is
    the half the provider treats as non-negotiable, and dropping it would
    widen an audience somebody deliberately narrowed, while dropping the
    inclusion removes nothing the exclusion was not already removing.
    """
    for name in choice.dropped:
        notes.append(
            Adjustment(field=AUDIENCE_FIELD, reason="audience_unavailable", detail=name)
        )

    excluded = _unique(choice.excluded)
    barred = {ref.external_id for ref in excluded}

    included: list[AudienceRef] = []
    for ref in _unique(choice.included):
        if ref.external_id in barred:
            notes.append(
                Adjustment(
                    field=INCLUDE_KEY,
                    reason="audience_on_both_sides",
                    detail=ref.label or ref.external_id,
                )
            )
            continue
        included.append(ref)

    _write(spec, INCLUDE_KEY, included)
    _write(spec, EXCLUDE_KEY, excluded)


def _unique(refs: tuple[AudienceRef, ...]) -> list[AudienceRef]:
    """The same audience twice on one side is one audience, silently.

    No adjustment: nothing was decided differently and nobody chose it
    twice on purpose. Order is kept so the spec reads the way the screen
    listed it.
    """
    seen: set[str] = set()
    kept: list[AudienceRef] = []
    for ref in refs:
        if not ref.external_id or ref.external_id in seen:
            continue
        seen.add(ref.external_id)
        kept.append(ref)
    return kept


def _write(spec: dict[str, Any], key: str, refs: list[AudienceRef]) -> None:
    """``[{"id": ...}]``, the shape the provider documents its example in.

    Bare ids are accepted too. The object form is chosen because it is what
    comes *back*: a spec read off an existing ad set is compared against
    the one that went out, and two spellings of one list would report a
    difference that is not one.
    """
    if not refs:
        spec.pop(key, None)
        return
    spec[key] = [{"id": ref.external_id} for ref in refs[:MAX_PER_SIDE]]


__all__ = [
    "AUDIENCE_FIELD",
    "EXCLUDE_KEY",
    "INCLUDE_KEY",
    "MAX_PER_SIDE",
    "AudienceChoice",
    "AudienceRef",
    "fit",
]
