"""Answers plus a preset, in - a targeting spec, out.

The whole package exists for this one function. Everything it needs arrives
as an argument: no clock, no database, no HTTP, no settings. That is what
makes it testable without a fixture and what will let a second provider be
added without touching it.
"""

from collections.abc import Mapping
from typing import Any, Final, cast

from adskit import MinorUnits

from core.targeting.adjustments import Adjustment, AdjustmentReason
from core.targeting.attribution import attribution_window, takes_attribution
from core.targeting.audiences import AudienceChoice
from core.targeting.budget import FREQUENCY_GOALS, accepts_cap, spend_limits_fit
from core.targeting.buttons import button
from core.targeting.campaign_types import campaign_type
from core.targeting.compat import needs_pixel
from core.targeting.contracts import (
    BuiltTargeting,
    BusinessProfile,
    ConversionSource,
    Interest,
    OnboardingAnswers,
    QualityLeads,
)
from core.targeting.conversion_events import (
    EVENT_KEY,
    conversion_event,
    events_for,
)
from core.targeting.destinations import AdDestination, needs_link
from core.targeting.destinations import channel as chat_channel
from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import GeoChoice, geo_locations
from core.targeting.modes import TargetingMode, wants_interests
from core.targeting.placements import keep_chat_reachable, pin_to_instagram
from core.targeting.presets import Preset, PresetCatalog
from core.targeting.quality import QUALITY_GOAL
from core.targeting.quality import goal_for as quality_goal
from core.targeting.render import render
from core.targeting.tracking import clean_tags, tags_are_usable
from core.targeting.validators import validate_structure


def build(
    *,
    provider: str,
    answers: OnboardingAnswers,
    business: BusinessProfile,
    catalog: PresetCatalog,
    currency: str,
    min_daily_minor: int = 0,
    geo: GeoChoice | None = None,
    conversion: ConversionSource | None = None,
    quality: QualityLeads | None = None,
    audiences: AudienceChoice | None = None,
    link: str = "",
    welcome: str = "",
    questions: tuple[str, ...] = (),
    phone: str = "",
) -> BuiltTargeting:
    """The spec for one campaign, ready to be reviewed or sent.

    Raises rather than returning a half-built object: a spec missing a field
    is not a smaller spec, it is a campaign that spends money on the wrong
    people. ``PresetNotFound``, ``UnfilledTemplate`` and ``BudgetTooLow``
    all mean stop.

    ``currency`` is the **ad account's**, not the advertiser's reporting
    preference, and it is an argument rather than a field on the profile
    because that is the only honest place for it: the budget below is sent
    as an integer count of the smallest unit of whichever currency the
    account is billed in, the provider will not convert, and this package
    cannot read a Django row to find out which that is. Passing the wrong
    one does not fail - it produces a legal number in the wrong
    denomination, which is how "50" becomes fifty so'm or fifty dollars
    depending on nothing the owner can see.

    ``geo`` replaces the preset's whole geography block, before rendering
    rather than after, and it is how a campaign gets aimed somewhere. The
    preset's own block is a shape rather than a decision - ten of the twelve
    draw a radius around a pin - and which pin, or whether a radius makes
    sense at all, is something only the owner knows: a delivery service
    covering a whole city has no radius, and a shop has no interest in a
    country.

    Passing nothing leaves the preset's block to render as written.

    The adjustment is reported for one case and not the others: a country
    nobody asked for. An owner who chose the whole country is not surprised
    by getting it, and telling them their audience was widened would be
    describing a decision back to the person who made it.

    ``conversion`` is where a sale on the advertiser's own website gets
    reported from - a Meta pixel, a Google conversion action. Optional, and
    absent for most launches: only the goals that optimise for an off-site
    event need one, and half the businesses this product is for have no
    website. When a preset asks for one and none is given, the spec is
    built anyway and says so through an adjustment; refusing here would
    stop somebody seeing their own proposal because of a thing they plug in
    afterwards. ``validate_launchable`` is what refuses.

    ``link`` is the advertiser's own address, and it matters on exactly the
    goals whose ad is a link. Carried straight through rather than
    validated: an empty one is normal on every other goal, and whether a
    given address is one the provider will accept is the provider's rule
    and not this package's business. ``validate_launchable`` refuses the
    one case that must not launch - a goal that sells a visit to a site
    nobody named.

    ``welcome`` is the first thing said in the conversation a chat ad
    opens, and it reads like ``link`` above without behaving like it: an
    empty one is **not** refused anywhere. The provider greets the customer
    itself when none is sent, so the worst an unanswered greeting produces
    is a working ad opening in the provider's words rather than the
    owner's - while an unanswered address produces a campaign spending
    money somewhere nobody chose. Two optional strings, two different
    kinds of optional, and only one of them has a gate.

    Nothing is substituted here when it is empty. The catalogue's own
    suggestion filled the box the owner then cleared, and putting it back
    would be answering a question on their behalf after they answered it.

    ``quality`` decides whether a lead campaign is bought on the owner's
    own verdicts instead of on form submissions. Optional and absent for
    almost every launch, like ``conversion`` above and for a similar reason:
    it needs something the account has to have earned - verdicts already
    being reported, and enough of them recently - and an account that has
    never marked a lead builds exactly the campaign the preset describes.
    Nothing is refused when it is missing; the goal simply stays
    the preset's own. See :mod:`core.targeting.quality` for the three
    conditions and why the owner's answer is one of them.

    ``phone`` is the number a call ad's button dials, already in E.164 -
    the third of these strings and the third kind of optional. It is
    carried straight through like the other two and checked in neither
    place it passes: whether it parses is the form's question, because
    that is where somebody can still see what they typed, and whether it
    is present is ``validate_launchable``'s. What must not happen here is
    a fallback, and it is the same fallback the address refuses: the
    business's own profile number would be a number nobody chose for this
    campaign, dialling a phone nobody was told would ring.
    """
    preset = catalog.find(
        provider=provider, category=answers.category, goal=answers.goal
    )
    # Which kind of campaign buys the goal. It changes the objective and the
    # optimisation goal and nothing else; a goal the table does not cover
    # keeps the preset's own.
    kind = campaign_type(provider=provider, goal=preset.goal, key=answers.campaign_type)
    objective = kind.objective if kind else preset.objective
    kind_goal = kind.optimization_goal if kind else preset.optimization_goal

    template: dict[str, Any] = dict(preset.targeting)
    notes: list[Adjustment] = []
    if geo is not None:
        template["geo_locations"] = geo_locations(geo)
        if geo.widened:
            notes.append(
                Adjustment(field="geo_locations", reason="location_missing", detail="")
            )

    spec: dict[str, Any] = render(
        template,
        sources={"business": business, "answers": answers},
        defaults=preset.defaults,
    )

    total_cap, limit_notes = _total_cap(answers)
    promoted, promotion_notes = _promoted_object(
        provider=provider,
        objective=objective,
        preset=preset,
        business=business,
        answers=answers,
        conversion=conversion,
    )
    notes.extend(promotion_notes)

    mode, mode_notes = _mode(business=business, answers=answers)
    notes.extend(mode_notes)

    chosen_audiences = audiences or AudienceChoice()

    confirmed = tuple(i for i in answers.interests if i.is_confirmed)
    if confirmed and wants_interests(mode):
        spec["flexible_spec"] = [_detailed(confirmed)]

    checked, checks = validate_structure(
        spec,
        special_ad_category=business.special_ad_category,
        daily_budget_minor=int(answers.daily_budget_minor),
        min_daily_minor=min_daily_minor,
        currency=currency,
        targeting_mode=mode,
        placement_mode=answers.placement_mode,
        audiences=chosen_audiences,
    )
    if preset.opens_profile:
        # The profile is on Instagram, so the advert is shown there only -
        # whatever the owner answered for every other goal.
        pin_to_instagram(checked, notes)
    elif preset.opens_chat:
        keep_chat_reachable(
            checked, notes, mode=answers.placement_mode, chat=answers.chat_channel
        )

    # The button and the ad set's destination. Off the preset for every
    # goal but one; a chat goal has neither, because the two are a pair
    # Meta refuses to see mismatched and which surface the conversation
    # opens on is the owner's answer rather than the category's.
    surface = chat_channel(answers.chat_channel)

    cap, cap_notes = _cost_cap(answers=answers, goal_of=kind_goal)
    notes.extend(cap_notes)
    notes.extend(limit_notes)

    wanted = quality or QualityLeads()
    goal = quality_goal(
        preset_goal=kind_goal,
        chosen=wanted.chosen,
        reporting=wanted.is_reporting,
        qualified_recently=wanted.qualified_recently,
    )

    return BuiltTargeting(
        objective=objective,
        optimization_goal=goal,
        billing_event=preset.billing_event,
        destination_type=(
            surface.destination_type if preset.opens_chat else preset.destination_type
        ),
        targeting=checked,
        daily_budget_minor=MinorUnits(int(answers.daily_budget_minor)),
        sends_to=preset.sends_to,
        call_to_action=_button(
            answers.call_to_action,
            provider=provider,
            sends_to=preset.sends_to,
            preset_word=(
                surface.call_to_action if preset.opens_chat else preset.call_to_action
            ),
        ),
        link_url=link,
        # Only where there is an address to append it to. A goal whose
        # advert opens a form or dials a number carries a link the provider
        # never follows, and tags on that one would describe visits nobody
        # can make.
        url_tags=_tags(answers.url_tags, sends_to=preset.sends_to),
        # Straight through, and never filled in from anywhere. See above.
        phone_number=phone,
        campaign_type=kind.key if kind else "",
        # The owner's, straight through - and the catalogue's beside it.
        # The second is never asked for: what the customer's own message
        # box opens pre-typed with follows from the goal, and asking a
        # restaurant to write the sentence its customer sends *to* it is
        # a question with no good answer on either side.
        welcome_text=welcome,
        autofill_text=preset.autofill_message,
        # Only beside a greeting: the provider's welcome screen has no
        # questions without the line above them.
        welcome_questions=questions if welcome and preset.opens_chat else (),
        # The account's, straight through. There is nothing to reconcile
        # and nothing to convert: the budget was typed in this currency
        # because the screen that asked for it was denominated in this
        # currency, and both come from the same row.
        currency=currency,
        special_ad_categories=_categories(business),
        special_ad_category_countries=_category_countries(
            business=business, targeting=spec, geo=geo
        ),
        preset_key=preset.key,
        preset_version=preset.version,
        targeting_mode=mode,
        # Straight off the answer, with no category override beside it.
        # A Special Ad Category overrules the audience mode above because
        # the provider is silent about whether the automation switch is
        # even accepted there; it is silent about placements too, and the
        # two silences do not mean the same thing. That one sits beside a
        # switch the category exists to regulate - who the audience is -
        # and this one does not. Narrowing delivery on a rule nobody wrote
        # would be inventing a restriction, which is the thing this
        # package refuses to do in every other place it has been tempted.
        placement_mode=answers.placement_mode,
        audiences=chosen_audiences,
        max_result_cost_minor=cap,
        # Only beside a goal counted on the advertiser's site - see
        # ``core.targeting.attribution.ATTRIBUTION_GOALS``.
        attribution_days=(
            _window(answers.attribution_key, provider=provider)
            if takes_attribution(goal)
            else None
        ),
        # Only where the provider takes it. A frequency cap on a goal
        # bought for taps is refused at creation, naming the field.
        frequency_cap=(answers.frequency_cap if goal in FREQUENCY_GOALS else None),
        total_cap_minor=total_cap,
        promoted_object=_quality_promotion(promoted, upgraded=goal),
        # The row's own rule where the table has one - see
        # ``core.targeting.compat`` - and the preset's for a goal it has none.
        needs_conversion_source=(
            needs_pixel(provider=provider, key=kind.key)
            if kind
            else preset.needs_conversion_source
        ),
        buys_qualified_leads=goal != kind_goal,
        adjustments=(
            *notes,
            *checks,
            # Only when the interests were going to be used. In a broad
            # audience they were not, so reporting them as dropped would be
            # telling somebody their choice failed when they had chosen not
            # to make it.
            *(_unconfirmed(answers.interests) if wants_interests(mode) else ()),
        ),
    )


def _mode(
    *, business: BusinessProfile, answers: OnboardingAnswers
) -> tuple[TargetingMode, list[Adjustment]]:
    """Which mode this spec is built as, after the law has had its say.

    A Special Ad Category overrules the answer, and it is the one thing
    that may. Those campaigns are the case where the provider's own
    documentation is silent - it says nothing about whether the automation
    switch is even accepted beside a category - and the honest reading of
    silence is the value that already works. ``0`` is what every one of
    these campaigns is sent, so forcing it here changes nothing about them
    and guesses nothing.

    The override is reported like every other thing a category removes, and
    under the same reason: the advertiser chose something and is getting
    something else, which is exactly what that box on the review screen is
    for.
    """
    if not business.special_ad_category:
        return answers.targeting_mode, []
    if answers.targeting_mode == "interests":
        return "interests", []
    return "interests", [
        Adjustment(
            field="targeting_automation",
            reason="special_ad_category",
            detail=business.special_ad_category,
        )
    ]


def _promoted_object(
    *,
    provider: str,
    objective: str,
    preset: Preset,
    business: BusinessProfile,
    answers: OnboardingAnswers,
    conversion: ConversionSource | None,
) -> tuple[dict[str, Any], list[Adjustment]]:
    """The off-site event this ad set optimises towards, if there is one.

    Rendered through the same placeholders as the targeting block, so a
    preset stays data: ``{conversion.external_id}`` is a hole with a name
    on it, not a branch.

    A missing source produces an empty object and a note, never a half
    filled one. ``promoted_object`` with a blank pixel id is the shape the
    provider accepts and then refuses to deliver on, which is a worse
    outcome than not sending it.
    """
    if not preset.needs_conversion_source:
        return {}, []

    if conversion is None or not conversion.is_usable:
        return {}, [
            Adjustment(
                field="promoted_object",
                reason="conversion_source_missing",
                detail=preset.goal,
            )
        ]

    rendered: dict[str, Any] = render(
        dict(preset.promoted_object),
        sources={"business": business, "answers": answers, "conversion": conversion},
        defaults=preset.defaults,
    )
    return (
        _counted_event(
            rendered,
            provider=provider,
            objective=objective,
            chosen=answers.conversion_event,
        ),
        [],
    )


def _counted_event(
    promoted: dict[str, Any], *, provider: str, objective: str, chosen: str
) -> dict[str, Any]:
    """The event this ad set is bought against, once the owner has had a say.

    Replaces the preset's own, and only where the preset named one: the key
    is what the provider reads, and adding it to an object that has none
    would name an event for a goal whose result the provider counts itself.

    An unnamed event leaves the preset's in place. So does one this package
    has no word for, and one the objective does not take - the provider
    refuses both with the ad set half made, and the preset's is the one
    shape known to work.
    """
    if not chosen or EVENT_KEY not in promoted:
        return promoted
    known = conversion_event(provider=provider, key=chosen)
    if known is None or known not in events_for(provider=provider, objective=objective):
        return promoted
    return dict(promoted) | {EVENT_KEY: known.key}


def _button(
    given: str, *, provider: str, sends_to: AdDestination, preset_word: str
) -> str:
    """The word on the button, once the provider has had a say.

    The catalogue's own unless the owner chose one this kind of advert may
    carry. A word the provider refuses on this destination is not sent: it
    would be refused on the last call of the sequence, with a campaign, an
    ad set and an upload already made.

    **The chat surfaces keep their own.** Which word an Instagram
    conversation advert takes is decided by the surface rather than by
    anybody's preference - see :mod:`core.targeting.destinations` - and
    letting a choice past here would produce the one refusal that module
    exists to prevent.
    """
    if not given or sends_to == "chat":
        return preset_word
    chosen = button(provider=provider, sends_to=sends_to, key=given)
    return chosen.key if chosen is not None else preset_word


def _window(key: str, *, provider: str) -> tuple[int, int] | None:
    """The chosen window as a pair of day counts, or ``None`` for the default.

    An unknown key answers ``None`` rather than falling back to the
    provider's published default, and the two are not the same: ``None``
    sends nothing at all, so the provider uses whatever it uses today - and
    a default copied into this package is a number that goes stale
    silently.
    """
    if not key:
        return None
    found = attribution_window(provider=provider, key=key)
    return None if found is None else (found.click_days, found.view_days)


def _total_cap(
    answers: OnboardingAnswers,
) -> tuple[MinorUnits | None, list[Adjustment]]:
    """The total ceiling, or none, with a note when it is dropped."""
    total = answers.total_cap_minor
    if not total:
        return None, []
    refused = spend_limits_fit(
        daily_minor=int(answers.daily_budget_minor), total_cap_minor=int(total)
    )
    if refused:
        return None, [
            Adjustment(
                field="spend_limits",
                # A string from the rule next door, and the type says which
                # ones it can be - see ``spend_limits_fit``.
                reason=cast(AdjustmentReason, refused),
                detail="",
            )
        ]
    return total, []


def _tags(given: str, *, sends_to: AdDestination) -> str:
    """The tracking query this advert should carry, once the goal has had a say.

    Dropped without a word for a goal that sends nobody to a website, and
    that silence is deliberate: an adjustment is for something the owner
    asked for and did not get, and nobody asks for tags on a form advert -
    the answer simply travels with a launch whose goal changed.

    A string the provider could not append is dropped too, for the reason
    the whole field is checked rather than trusted: the provider accepts a
    malformed tail and serves adverts with it, and every visit then arrives
    in the advertiser's own analytics attributed to nothing.
    """
    if not needs_link(sends_to) or not tags_are_usable(given):
        return ""
    return clean_tags(given)


def _cost_cap(
    *, answers: OnboardingAnswers, goal_of: str
) -> tuple[MinorUnits | None, list[Adjustment]]:
    """The most-per-result figure, once the goal has had a say.

    Dropped rather than refused when the goal cannot carry one, and
    reported like every other thing this package removes. The alternative -
    raising here - would stop somebody seeing their own proposal because of
    an answer they gave on a screen two steps back about a goal they have
    since changed, which is exactly the failure ``conversion`` next door is
    shaped to avoid.

    An unusable *pairing* is a different matter and is not decided here.
    Whether the daily budget can pace against this cap is arithmetic about
    money, like the budget floor, and it is refused rather than corrected -
    in :func:`core.targeting.gate.validate_launchable`.
    """
    given = answers.max_result_cost_minor
    if given is None or given <= 0:
        return None, []
    if not accepts_cap(goal_of):
        return None, [
            Adjustment(
                field="bid_amount", reason="goal_takes_no_cap", detail=str(given)
            )
        ]
    return MinorUnits(int(given)), []


def _quality_promotion(promoted: dict[str, Any], *, upgraded: str) -> dict[str, Any]:
    """What a quality-lead ad set has to say it is optimising towards.

    Meta refuses ``QUALITY_LEAD`` on an ad set that does not name the event
    it counts, and the event for a form the provider hosts is its own
    ``LEAD`` - not a pixel's. The page half of the object is added a layer
    up, where a page id exists; this package has never heard of one and
    must not start.

    **The dataset is deliberately not named here.** The verdicts are filed
    against it by the reporting sweep, and the ad set's link to them is the
    account-level integration rather than a field on this object. If the
    provider turns out to want it here as well, the refusal arrives at
    creation time with the field named - which is the loud failure this
    shape was chosen for, against the alternative of an ad set Meta accepts
    and delivers against nothing.

    Untouched for every other goal, including one that already carries a
    pixel: a website campaign's promoted object is the preset's and is not
    this function's business.
    """
    if upgraded != QUALITY_GOAL:
        return promoted
    return dict(promoted) | {"custom_event_type": "LEAD"}


# Which key of the provider's detailed-targeting block each kind goes into.
#
# Provider vocabulary, and one of the few places this package spells it -
# for the reason ``optimization_goal`` is spelled here: the spec is what
# gets sent, and there is no second platform yet to abstract the block's
# shape over.
#
# **A row in the wrong key is not refused.** Meta accepts a life event
# posted under ``interests``, matches it against nobody, and delivers an
# audience narrower than anybody chose - with no error and nothing in
# ``dropped`` to find it by. Which is why the mapping is a table read off
# :data:`adskit.TraitKind` rather than a branch anybody could forget to
# extend.
DETAILED_KEYS: dict[str, str] = {
    "interest": "interests",
    "behaviour": "behaviors",
    "life_event": "life_events",
}


def _detailed(confirmed: tuple[Interest, ...]) -> dict[str, list[dict[str, str]]]:
    """One flexible-spec block, with each kind under its own key.

    **One block and not three, which is a decision about what the campaign
    means.** Keys inside a single block are OR-ed by the provider and
    separate blocks are AND-ed, so three blocks would target somebody who is
    interested in furniture *and* has recently moved *and* shops online -
    which is a fraction of a fraction and is nobody's intent here. One block
    widens: anybody who matches any of them.

    Empty kinds are absent rather than empty. An empty list is an error on
    some of these keys and a silent no-op on others, which is the worst of
    both - the same rule ``_drop_empty`` applies to the spec around it.
    """
    block: dict[str, list[dict[str, str]]] = {}
    for item in confirmed:
        key = DETAILED_KEYS.get(item.kind)
        if key is None:
            # A kind nobody mapped is dropped rather than guessed into a
            # key. Unreachable from the catalogue, reachable from a
            # hand-edited draft, and silence is the safe direction: the
            # audience is wider than intended rather than aimed at
            # strangers.
            continue
        block.setdefault(key, []).append(_interest(item))
    return block


def _interest(interest: Interest) -> dict[str, str]:
    """Both halves travel. The name is what a person can check later."""
    return {"id": interest.external_id, "name": interest.query}


def _unconfirmed(interests: tuple[Interest, ...]) -> tuple[Adjustment, ...]:
    """Names the provider never confirmed, reported one by one.

    Dropped from the spec but not from the conversation: the owner picked
    these, and a list that quietly shrinks between one screen and the next
    is how trust in the whole flow goes.
    """
    return tuple(
        Adjustment(
            field="flexible_spec",
            reason="unconfirmed_interest",
            detail=interest.label,
        )
        for interest in interests
        if not interest.is_confirmed
    )


# The provider's spelling of each regulated category, keyed by ours. Meta
# retired CREDIT in January 2025 and refuses it; the same businesses are
# declared under the wider FINANCIAL_PRODUCTS_SERVICES.
SPECIAL_AD_CATEGORIES: Final[dict[str, str]] = {
    "housing": "HOUSING",
    "employment": "EMPLOYMENT",
    "credit": "FINANCIAL_PRODUCTS_SERVICES",
}


def _categories(business: BusinessProfile) -> tuple[str, ...]:
    """A tuple of at most one. The provider's field is a list, and the
    business profile holds a single value - housing, employment or credit -
    because no business is two of them at once.

    An unknown value is refused here rather than sent: Meta answers it with
    a bare "invalid parameter" on the first call of the sequence.
    """
    category = business.special_ad_category.strip().lower()
    if not category:
        return ()
    if category not in SPECIAL_AD_CATEGORIES:
        raise InvalidTargeting(
            f"unknown special ad category {category!r}",
            field="special_ad_category",
        )
    return (SPECIAL_AD_CATEGORIES[category],)


def _category_countries(
    *, business: BusinessProfile, targeting: Mapping[str, Any], geo: GeoChoice | None
) -> tuple[str, ...]:
    """The countries a regulated campaign runs in.

    The ones the targeting names; a campaign aimed at a pin or at cities
    names none, and its country is the one the geography answer falls back
    to, else the business's own.
    """
    if not business.special_ad_category.strip():
        return ()
    named = (targeting.get("geo_locations") or {}).get("countries") or [
        (geo.country_code if geo else "") or business.country_code
    ]
    return tuple(sorted({str(code).upper() for code in named if code}))
