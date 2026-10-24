"""The last gate before the provider is called."""

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
    """The last gate before the provider is called."""
    if built.needs_link and not built.link_url:
        raise DestinationLinkMissing(
            "this goal is a visit to the advertiser's site and none is named"
        )

    if built.needs_phone and not built.phone_number:
        raise PhoneNumberMissing(
            "this goal is a phone call and no number was given to dial"
        )

    cap = built.max_result_cost_minor
    if cap and not cap_fits(
        cap_minor=int(cap), daily_budget_minor=int(built.daily_budget_minor)
    ):
        raise CostCapTooLow(
            cap_minor=int(cap),
            daily_minor=int(built.daily_budget_minor),
            needed_minor=min_daily_for_cap(cap_minor=int(cap)),
        )

    if built.needs_conversion_source and not built.promoted_object:
        raise ConversionSourceMissing(
            "this goal optimises for an off-site event and nothing reports one"
        )

    if built.special_ad_categories:
        barred = built.audiences.lookalikes
        if barred:
            raise LookalikeNotAllowed(
                labels=tuple(ref.label or ref.external_id for ref in barred)
            )

    waiting = built.audiences.unusable
    if waiting:
        raise AudienceUnusable(
            labels=tuple(ref.label or ref.external_id for ref in waiting)
        )

    if built.special_ad_categories:
        return
    if not requires_interests(built.targeting_mode):
        return
    if built.audiences.included:
        return
    if not built.targeting.get("flexible_spec"):
        raise NoInterestsChosen(
            "no confirmed interest survived; at least one is required"
        )
