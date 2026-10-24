"""The last gate before the provider is called.

Apart from :mod:`core.targeting.validators`, and along the seam that
module's own docstring names: **most checks correct rather than refuse.**
That one pulls a radius inside the allowed band and says so; this one has
exactly six rules and every one of them stops a launch dead.

Separate from ``validate_structure`` in *time* as well as in kind. The
wizard runs end to end with no provider connected, and at that point no
interest can carry a confirmed id, no pixel has been chosen and no
audience has finished counting. Refusing any of that while somebody is
still writing their proposal would make the product unusable until an
account was linked; refusing it here refuses exactly one thing - sending
a campaign that would spend money on something nobody agreed to.

**The order is load-bearing and is not alphabetical.** Each comment below
says why its rule sits where it does.
"""

from core.targeting.budget import cap_fits, min_daily_for_cap
from core.targeting.contracts import BuiltTargeting
from core.targeting.exceptions import (
    AudienceUnusable,
    ConversionSourceMissing,
    CostCapTooLow,
    DestinationLinkMissing,
    LookalikeNotAllowed,
    NoInterestsChosen,
    PhoneNumberMissing,
)
from core.targeting.modes import requires_interests


def validate_launchable(built: BuiltTargeting) -> None:
    """The last gate before the provider is called.

    Separate from ``validate_structure`` because the wizard runs end to end
    with no connection at all, and at that point no interest can carry a
    confirmed id yet. Refusing there would make the product unusable until
    the account is linked; refusing here refuses exactly one thing - sending
    a spec that targets nobody in particular.
    """
    # First of the five. The last three refuse a campaign aimed at the
    # wrong audience; this one refuses a campaign that would send the
    # advertiser's own paid traffic to an address nobody named - and would
    # look like a success from every screen while doing it.
    if built.needs_link and not built.link_url:
        raise DestinationLinkMissing(
            "this goal is a visit to the advertiser's site and none is named"
        )

    # Second, and the same rule one destination along. Both refuse an ad
    # whose button has nowhere to send anybody, and the reason they are two
    # rules rather than one is that they fail differently: an address is
    # missing and the creative is refused, while a **number** is missing and
    # the creative is accepted - the button falls back to carrying a link,
    # because that is the other branch of the very key Meta reads it from.
    #
    # So this is the more dangerous of the two and it is checked here rather
    # than at the provider, which would never complain. Whether the number
    # can be dialled from where the ad runs is asked at the form, where
    # somebody can still see what they typed; what is asked here is only
    # whether there is one at all.
    if built.needs_phone and not built.phone_number:
        raise PhoneNumberMissing(
            "this goal is a phone call and no number was given to dial"
        )

    # Arithmetic about money, so it is refused rather than corrected - the
    # same treatment ``BudgetTooLow`` gets, and for the same reason: raising
    # a cap somebody typed would be deciding on their behalf what a customer
    # is worth to them.
    #
    # Here rather than at the provider because the provider accepts this
    # pair. An ad set with a cap its budget cannot pace against delivers to
    # nobody and reports no spend, no leads and no cost per lead - which is
    # indistinguishable, on every screen this product has, from a campaign
    # that has not started yet.
    cap = built.max_result_cost_minor
    if cap and not cap_fits(
        cap_minor=int(cap), daily_budget_minor=int(built.daily_budget_minor)
    ):
        raise CostCapTooLow(
            cap_minor=int(cap),
            daily_minor=int(built.daily_budget_minor),
            needed_minor=min_daily_for_cap(cap_minor=int(cap)),
        )

    # Checked before the interest rule, because it is the one the owner can
    # do something about right now: plugging a pixel in is a screen away,
    # while an interest nobody confirmed needs the lookup to run again.
    if built.needs_conversion_source and not built.promoted_object:
        raise ConversionSourceMissing(
            "this goal optimises for an off-site event and nothing reports one"
        )

    # One rule survives a Special Ad Category rather than being replaced by
    # it, and it is the provider's own: a lookalike audience is *removed*
    # for housing, employment and credit, while an ordinary custom audience
    # stays available on both sides. Sending one is not refused - it is
    # accepted, run at ``WITH_ISSUES`` and never delivered, which is why it
    # has to be caught here.
    #
    # First of the two audience rules, because it is the more specific: a
    # lookalike beside a category is also unusable, and being told to wait
    # for something that will never become allowed is worse than being told
    # nothing.
    if built.special_ad_categories:
        barred = built.audiences.lookalikes
        if barred:
            raise LookalikeNotAllowed(
                labels=tuple(ref.label or ref.external_id for ref in barred)
            )

    # Inside a category and outside one, because the fix is the same
    # either way: an audience the provider will not deliver on is one this
    # launch has to wait for or let go of.
    waiting = built.audiences.unusable
    if waiting:
        raise AudienceUnusable(
            labels=tuple(ref.label or ref.external_id for ref in waiting)
        )

    if built.special_ad_categories:
        return
    # **Read off the mode, never off the spec.** An advertiser who chose a
    # broad audience and one whose interests all failed confirmation
    # produce the identical targeting block, and only the first of them may
    # launch. Asking the spec would make the second indistinguishable from
    # the first - which is the accident this gate was written to catch, and
    # the exact way it would have stopped catching it the day a second mode
    # existed.
    if not requires_interests(built.targeting_mode):
        return
    # **An audience of named people is a targeted audience.** The rule
    # above is about absence, which is ambiguous - no detailed targeting
    # can be a choice or an accident. This one is about presence, which
    # never is: an interest lookup that finds nothing cannot leave a custom
    # audience behind, so a spec holding one was aimed by somebody. The
    # asymmetry is what lets this be read off the built choice without
    # reopening the hole the mode was carried to close.
    if built.audiences.included:
        return
    if not built.targeting.get("flexible_spec"):
        raise NoInterestsChosen(
            "no confirmed interest survived; at least one is required"
        )
