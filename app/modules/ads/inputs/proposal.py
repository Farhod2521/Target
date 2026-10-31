"""The review screen's save: every section that was sent, checked whole.

A section left out of the body is left alone, and so is a field left out of
a section that was sent: it is read from the launch before the section is
checked, so the services below still see a whole answer. Nothing is written
unless every section passes.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Final

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.money import provider_money
from app.modules.ads import audiences as audience_field
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    ATTRIBUTION,
    FREQUENCY_CAP,
    GEO_AROUND,
    GEO_MODE_CHOICES,
    MAX_GEO_PLACES,
    PRIMARY_TEXT_MAX,
    DraftSection,
    FormDepth,
    LeadBuying,
    PlacementMode,
    TargetingMode,
)
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.ending import check_ending
from app.modules.ads.inputs.proposal_body import (
    AdvancedIn,
    AudienceIn,
    CreativeIn,
    FormSectionIn,
    ProposalIn,
)
from app.modules.ads.inputs.questions import read_rows, rows_error
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.audiences_chosen import area_options
from app.modules.ads.selectors.conversion_event import offered_events
from app.modules.ads.selectors.delivery_options import cost_cap_choice
from app.modules.ads.selectors.goals import goal_preset
from app.modules.ads.selectors.lead_form import default_title, kept_questions
from app.modules.ads.selectors.pixel import usable_pixels
from app.modules.ads.selectors.review_proposal import (
    merged_questions,
    offered_interests,
)
from app.modules.ads.selectors.tracking import effective_url_tags, offered_buttons
from app.modules.ads.selectors.variants import (
    launch_variants,
    post_caption_of,
    same_words,
)
from app.modules.ads.services.advanced import AdvancedEdit, CreativeEdit
from app.modules.ads.services.locations import confirmed_places
from app.modules.businesses.models import Business
from app.modules.integrations.selectors.audiences import targets_for
from core.targeting import MAX_AGE, MIN_AGE, GeoChoice
from core.targeting.attribution import windows_for
from core.targeting.campaign_types import types_for
from core.targeting.modes import DEFAULT_TARGETING_MODE

PIN_PRECISION = Decimal("0.000001")
NO_FORM: Final = "Bu maqsadning reklamasida lid-forma yo'q."
NO_ADVANCED: Final = "Bu maqsadda «Kengaytirilgan» bo'limi yo'q."


def check_proposal(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    body: ProposalIn,
    plan_owns_kind: bool,
) -> dict[str, Any]:
    """The keyword arguments ``save_proposal`` takes, or :class:`InputRefused`."""
    problems = Problems()
    draft = launch.draft or {}
    answers: dict[str, Any] = {}
    if body.audience is not None:
        answers["audience"] = _audience(
            db,
            launch=launch,
            business=business,
            body=_kept(body.audience, _audience_now(launch)),
            problems=problems,
        )
    if body.interests is not None:
        interests = _kept(
            body.interests,
            {
                "queries": [
                    str(item.get("query", ""))
                    for item in draft_field.chosen(draft, DraftSection.INTERESTS) or []
                ]
            },
        )
        offered = offered_interests(
            proposed=draft_field.proposal(draft, DraftSection.INTERESTS) or [],
            chosen=draft_field.chosen(draft, DraftSection.INTERESTS) or [],
        )
        known = {str(item.get("query", "")) for item in offered}
        if any(query not in known for query in interests.queries):
            problems.add("interests.queries", "Ro'yxatdan tanlang.")
        answers["interests"] = {
            "queries": list(interests.queries),
            "added": [line.strip() for line in interests.added if line.strip()],
        }
    if body.traits is not None:
        proposed = draft_field.proposal(draft, DraftSection.TRAITS) or []
        picked = set(body.traits)
        answers["traits"] = [
            {
                "label": str(item.get("label", "")),
                "query": str(item.get("query", "")),
                "kind": str(item.get("kind", "")),
                "external_id": str(item.get("external_id", "")),
            }
            for item in proposed
            if item.get("query") in picked
        ]
    if body.creatives is not None:
        answers["creatives"] = _creatives(
            db, launch=launch, body=body.creatives, problems=problems
        )
    if body.form is not None:
        preset = goal_preset(db, launch=launch)
        if preset is None or not preset.needs_lead_form:
            problems.add("form", NO_FORM)
        else:
            answers |= _form(
                launch=launch,
                business=business,
                body=_kept(body.form, {"lead_form": launch.lead_form_external_id}),
                problems=problems,
            )
    if body.advanced is not None and not _kinds(launch):
        problems.add("advanced", NO_ADVANCED)
    elif body.advanced is not None:
        answers["advanced"] = _advanced(
            db,
            launch=launch,
            body=body.advanced,
            problems=problems,
            plan_owns_kind=plan_owns_kind,
        )
    problems.refuse()
    return answers


def _kept[M: BaseModel](body: M, now: dict[str, Any]) -> M:
    """``body`` with every field it left out taken from ``now``."""
    return body.model_copy(
        update={
            name: value
            for name, value in now.items()
            if name not in body.model_fields_set
        }
    )


def _kinds(launch: CampaignLaunch) -> list[str]:
    """The campaign types this goal is bought as; none, and there is no tab."""
    goal = str(launch.answers.get("goal") or "")
    return [row.key for row in types_for(provider=launch.provider, goal=goal)]


def _audience_now(launch: CampaignLaunch) -> dict[str, Any]:
    """The audience as the launch holds it, in the shape the section is sent."""
    chosen = draft_field.chosen(launch.draft or {}, DraftSection.AUDIENCE) or {}
    geo = geo_field.stored(chosen)
    known = {row.get("key", "") for row in geo_field.known_places(chosen)}
    return {
        "targeting_mode": str(chosen.get("targeting_mode") or DEFAULT_TARGETING_MODE),
        "placement_mode": str(chosen.get("placement_mode") or ""),
        "lead_buying": LeadBuying.QUALITY
        if launch.buy_qualified_leads
        else LeadBuying.VOLUME,
        "age_min": int(chosen.get("age_min") or MIN_AGE),
        "age_max": int(chosen.get("age_max") or MAX_AGE),
        "genders": [int(gender) for gender in chosen.get("genders") or []],
        "geo_mode": str(geo.get("mode") or ""),
        "places": [
            str(row.get("key", ""))
            for row in geo.get("places") or []
            if isinstance(row, dict) and row.get("key") in known
        ],
        "areas": [row["area"] for row in geo_field.areas(chosen)],
        "radius_km": chosen.get("radius_km"),
        "lat": _degrees(geo.get("lat")),
        "lng": _degrees(geo.get("lng")),
        "address": str(geo.get("address") or ""),
        "audiences": audience_field.roles(chosen),
    }


def _degrees(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _choice(value: str, allowed: list[str], *, field: str, problems: Problems) -> str:
    if value and value not in allowed:
        problems.add(field, "Ro'yxatdan tanlang.")
    return value


def _audience(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    body: AudienceIn,
    problems: Problems,
) -> dict[str, Any]:
    chosen = draft_field.chosen(launch.draft or {}, DraftSection.AUDIENCE)
    _choice(
        body.targeting_mode,
        TargetingMode.values,
        field="audience.targeting_mode",
        problems=problems,
    )
    _choice(
        body.placement_mode,
        PlacementMode.values,
        field="audience.placement_mode",
        problems=problems,
    )
    _choice(
        body.lead_buying,
        LeadBuying.values,
        field="audience.lead_buying",
        problems=problems,
    )
    _choice(
        body.geo_mode or "?",
        [value for value, _ in GEO_MODE_CHOICES],
        field="audience.geo_mode",
        problems=problems,
    )
    places = {row.get("key", "") for row in geo_field.known_places(chosen)}
    if any(key not in places for key in body.places):
        problems.add("audience.places", "Ro'yxatdan tanlang.")
    areas = {row["key"] for row in area_options(db, country_code=business.country_code)}
    areas |= {row["area"] for row in geo_field.areas(chosen)}
    if any(key not in areas for key in body.areas):
        problems.add("audience.areas", "Ro'yxatdan tanlang.")
    picked = confirmed_places(
        db, launch=launch, picked=[pick.model_dump() for pick in body.picked]
    )
    if picked is None:
        problems.add("audience.places", "Ro'yxatdan tanlang.")
    elif picked and len(body.places) + len(picked) + len(body.areas) > MAX_GEO_PLACES:
        problems.add("audience.places", f"Ko'pi bilan {MAX_GEO_PLACES} ta joy.")
    if body.age_min > body.age_max:
        problems.add("audience", "Yosh oralig'i teskari kiritilgan.")
    pin = ("", "")
    if body.lat is not None and body.lng is not None:
        pin = (
            str(body.lat.quantize(PIN_PRECISION)),
            str(body.lng.quantize(PIN_PRECISION)),
        )
    if body.geo_mode == GEO_AROUND:
        if not body.radius_km:
            problems.add("audience.radius_km", "Masofani kiriting.")
        if not GeoChoice(lat=pin[0], lng=pin[1]).has_pin:
            problems.add("audience.geo_mode", "Xaritada joyni belgilang.")
    options = targets_for(
        db,
        owner=launch.owner,
        account=launch.ad_account,
        special_ad_category=business.special_ad_category,
    )
    labels = {option.key: option.label for option in options}
    roles = {key: role for key, role in body.audiences.items() if key in labels}
    return {
        "age_min": body.age_min,
        "age_max": body.age_max,
        "genders": [int(gender) for gender in body.genders],
        "radius_km": body.radius_km,
        "targeting_mode": body.targeting_mode or TargetingMode.AUTOMATIC,
        "placement_mode": body.placement_mode or PlacementMode.AUTOMATIC,
        "lead_buying": body.lead_buying,
        "audiences": audience_field.from_roles(roles, labels=labels),
        "geo_mode": body.geo_mode,
        "place_keys": list(body.places),
        "added": [line.strip() for line in body.added if line.strip()],
        "picked": picked or [],
        "area_keys": list(body.areas),
        "pin": pin,
        "address": body.address.strip(),
    }


def _creatives(
    db: Session, *, launch: CampaignLaunch, body: list[CreativeIn], problems: Problems
) -> list[CreativeEdit]:
    """One edit per advert; a post's untouched caption is the post's own."""
    by_position = {
        variant.position: variant for variant in launch_variants(db, launch=launch)
    }
    edits: list[CreativeEdit] = []
    for number, sent in enumerate(body, start=1):
        variant = by_position.get(sent.position)
        field = f"creatives.{number}"
        if variant is None:
            problems.add(field, f"{number}-reklama topilmadi.")
            continue
        item = _kept(
            sent,
            {
                "headline": variant.headline,
                "description": variant.description,
                "ad_name": variant.ad_name,
            },
        )
        caption = post_caption_of(variant)
        text = item.primary_text.strip()
        if "primary_text" not in sent.model_fields_set:
            text = variant.primary_text
        elif caption is not None and same_words(text, caption):
            text = caption
        elif not text:
            problems.add(
                f"{field}.primary_text", f"{number}-reklama: asosiy matnni yozing."
            )
        elif len(text) > PRIMARY_TEXT_MAX:
            problems.add(
                f"{field}.primary_text",
                f"{number}-reklama: asosiy matn {PRIMARY_TEXT_MAX} belgidan oshmasin.",
            )
        edits.append(
            CreativeEdit(
                position=item.position,
                primary_text=text,
                headline=(item.headline or "").strip(),
                description=(item.description or "").strip(),
                ad_name=(item.ad_name or "").strip(),
            )
        )
    return edits


def _form(
    *,
    launch: CampaignLaunch,
    business: Business,
    body: FormSectionIn,
    problems: Problems,
) -> dict[str, Any]:
    if body.form_depth and body.form_depth not in FormDepth.values:
        problems.add("form.form_depth", "Ro'yxatdan tanlang.")
    lead_form = (body.lead_form or "").strip()
    new_form = not lead_form
    answers: dict[str, Any] = {
        "lead_form": lead_form,
        "form_depth": body.form_depth,
        "questions": None,
        "ending": None,
    }
    if body.higher_intent is not None and body.form_depth:
        answers["higher_intent"] = body.higher_intent
    if new_form and body.ending is not None:
        answers["ending"] = check_ending(
            body.ending,
            region=business.country_code,
            default_title=default_title(business),
            problems=problems,
        )
    if new_form and body.rows is not None:
        offered = {
            str(item.get("kind", ""))
            for item in [
                *merged_questions(launch.draft or {}),
                *kept_questions(launch=launch),
            ]
        }
        edit = read_rows(body.rows, offered=offered)
        if error := rows_error(edit):
            problems.add("form.rows", error)
        answers["questions"] = edit.as_kwargs()
    return answers


def _advanced(
    db: Session,
    *,
    launch: CampaignLaunch,
    body: AdvancedIn,
    problems: Problems,
    plan_owns_kind: bool,
) -> AdvancedEdit:
    sent = body.model_fields_set
    answers = launch.answers or {}
    times, days = [*(answers.get(FREQUENCY_CAP) or []), None, None][:2]
    body = _kept(
        body,
        {
            "url_tags": effective_url_tags(db, launch=launch),
            "end_date": launch.end_date,
            "attribution": str(answers.get(ATTRIBUTION) or ""),
            "cap_times": times,
            "cap_days": days,
        },
    )
    _choice(
        body.campaign_type,
        _kinds(launch),
        field="advanced.campaign_type",
        problems=problems,
    )
    _choice(
        body.conversion_event,
        [row.key for row in offered_events(db, launch=launch)],
        field="advanced.conversion_event",
        problems=problems,
    )
    _choice(
        body.pixel_id,
        [row.external_id for row in usable_pixels(db, launch=launch)],
        field="advanced.pixel_id",
        problems=problems,
    )
    _choice(
        body.call_to_action,
        [row.key for row in offered_buttons(db, launch=launch)],
        field="advanced.call_to_action",
        problems=problems,
    )
    _choice(
        body.attribution or "",
        [row.key for row in windows_for(provider=launch.provider)],
        field="advanced.attribution",
        problems=problems,
    )
    return AdvancedEdit(
        campaign_type="" if plan_owns_kind else body.campaign_type,
        conversion_event=body.conversion_event,
        pixel_id=body.pixel_id,
        call_to_action=body.call_to_action,
        url_tags=body.url_tags or "",
        end_date=body.end_date,
        # Django's rule: no box for it any more, so a total left on an older
        # preparation is cleared rather than carried onto a shared campaign.
        total_cap_minor=None,
        max_result_cost_minor=_cost_cap(
            db, launch=launch, amount=body.max_result_cost, problems=problems
        )
        if "max_result_cost" in sent
        else None,
        attribution=body.attribution or "",
        cap_times=body.cap_times,
        cap_days=body.cap_days,
    )


def _cost_cap(
    db: Session, *, launch: CampaignLaunch, amount: Decimal | None, problems: Problems
) -> int | None:
    """Zero for an emptied box; ``None`` when the tab offers no box at all."""
    if cost_cap_choice(db, launch=launch) is None:
        return None
    if amount is None:
        return 0
    money = provider_money(provider=launch.provider)
    step = Decimal(1).scaleb(-money.decimal_places(launch.currency))
    try:
        if amount != amount.quantize(step):
            raise InvalidOperation
    except InvalidOperation:
        problems.add("advanced.max_result_cost", "Summani to'g'ri yozing.")
        return 0
    return money.to_minor(amount=amount, currency=launch.currency)


__all__ = ["ProposalIn", "check_proposal"]
