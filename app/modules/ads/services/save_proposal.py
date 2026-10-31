"""Every section of the proposal, written in one go or not at all."""

from typing import Any

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.ads import edits
from app.modules.ads.constants import ATTRIBUTION, FREQUENCY_CAP, HIGHER_INTENT
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.campaign_type import (
    campaign_type_locked,
    effective_campaign_type,
)
from app.modules.ads.selectors.conversion_event import effective_conversion_event
from app.modules.ads.selectors.lead_form import depth_changeable
from app.modules.ads.selectors.pixel import chosen_pixel
from app.modules.ads.selectors.proposal_changes import proposal_snapshot, same_value
from app.modules.ads.selectors.schedule import offered_days
from app.modules.ads.selectors.tracking import (
    effective_button,
    effective_url_tags,
    goal_sends_to_a_site,
)
from app.modules.ads.services.advanced import (
    AdvancedEdit,
    BudgetEdit,
    CreativeEdit,
    choose_attribution,
    choose_budget,
    choose_button,
    choose_campaign_type,
    choose_conversion_event,
    choose_cost_cap,
    choose_end_date,
    choose_form_intent,
    choose_frequency_cap,
    choose_pixel,
    choose_spend_limits,
    choose_url_tags,
)
from app.modules.ads.services.choices import (
    save_audience,
    save_creative,
    save_interests,
    save_questions,
    save_traits,
)
from app.modules.ads.services.forms import (
    apply_form_depth,
    choose_form_ending,
    choose_lead_form,
)
from app.modules.ads.services.interests import request_confirmation, request_estimate
from app.modules.ads.services.locations import request_locations
from app.modules.ads.services.targeting import rebuild_targeting
from app.modules.businesses.models import Business
from core.leads.ending import FormEnding
from core.targeting import clean_tags


def save_proposal(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    audience: dict[str, Any] | None = None,
    interests: dict[str, Any] | None = None,
    traits: list[dict[str, Any]] | None = None,
    creatives: list[CreativeEdit] | None = None,
    lead_form: str | None = None,
    questions: dict[str, Any] | None = None,
    ending: FormEnding | None = None,
    form_depth: str = "",
    higher_intent: bool | None = None,
    advanced: AdvancedEdit | None = None,
    budget: BudgetEdit | None = None,
) -> None:
    """Apply the sections that were sent. The caller commits, or rolls all back."""
    before = proposal_snapshot(db, launch=launch)
    if budget is not None:
        choose_budget(db, launch=launch, level=budget.level, sharing=budget.sharing)
    if advanced is not None and _apply_advanced(db, launch=launch, edit=advanced):
        rebuild_targeting(db, launch=launch, business=business)
        db.flush()
    places_typed = False
    if audience is not None:
        places_typed = save_audience(db, launch=launch, business=business, **audience)
    if interests is not None:
        save_interests(db, launch=launch, business=business, **interests)
    if traits is not None:
        save_traits(db, launch=launch, business=business, traits=traits)
    for creative in creatives or ():
        save_creative(
            db,
            launch=launch,
            business=business,
            position=creative.position,
            primary_text=creative.primary_text,
            headline=creative.headline,
            description=creative.description,
            ad_name=creative.ad_name,
        )
    if lead_form is not None:
        if form_depth and depth_changeable(db, launch=launch):
            apply_form_depth(db, launch=launch, depth=form_depth)
        choose_lead_form(db, launch=launch, external_id=lead_form)
        if not lead_form and questions is not None:
            save_questions(db, launch=launch, business=business, **questions)
        if not lead_form and ending is not None:
            choose_form_ending(db, launch=launch, business=business, ending=ending)
    if (
        higher_intent is not None
        and higher_intent != bool((launch.answers or {}).get(HIGHER_INTENT))
        and not campaign_type_locked(launch=launch)
    ):
        choose_form_intent(db, launch=launch, higher=higher_intent)
    if interests is not None or traits:
        request_confirmation(db, launch)
    elif audience is not None or traits is not None:
        request_estimate(db, launch)
    if places_typed:
        request_locations(db, launch)
    db.flush()
    db.refresh(launch)
    edits.record(
        fresh(launch, "draft"),
        before=before,
        after=proposal_snapshot(db, launch=launch),
        same=same_value,
    )
    db.flush()


def _apply_advanced(db: Session, *, launch: CampaignLaunch, edit: AdvancedEdit) -> bool:
    """Record whatever the advanced tab actually changed. True if anything did."""
    if campaign_type_locked(launch=launch):
        return False
    changed = False
    if edit.campaign_type and edit.campaign_type != effective_campaign_type(
        launch=launch
    ):
        choose_campaign_type(db, launch=launch, key=edit.campaign_type)
        changed = True
    if edit.conversion_event and edit.conversion_event != effective_conversion_event(
        db, launch=launch
    ):
        choose_conversion_event(db, launch=launch, key=edit.conversion_event)
        changed = True
    chosen = chosen_pixel(db, launch=launch)
    if edit.pixel_id and edit.pixel_id != (
        chosen.external_id if chosen is not None else ""
    ):
        choose_pixel(db, launch=launch, external_id=edit.pixel_id)
        changed = True
    if edit.call_to_action and edit.call_to_action != effective_button(
        db, launch=launch
    ):
        choose_button(db, launch=launch, key=edit.call_to_action)
        changed = True
    if goal_sends_to_a_site(db, launch=launch) and clean_tags(
        edit.url_tags
    ) != effective_url_tags(db, launch=launch):
        choose_url_tags(db, launch=launch, tags=edit.url_tags)
        changed = True
    if edit.end_date != launch.end_date:
        choose_end_date(
            db,
            launch=launch,
            day=edit.end_date,
            today=offered_days(launch=launch, now=utcnow())[0],
        )
        changed = True
    if edit.total_cap_minor != launch.total_cap_minor:
        choose_spend_limits(db, launch=launch, total_minor=edit.total_cap_minor)
        changed = True
    cap = edit.max_result_cost_minor
    if cap is not None and (cap or None) != launch.max_result_cost_minor:
        choose_cost_cap(db, launch=launch, amount_minor=cap)
        changed = True
    if edit.attribution != str((launch.answers or {}).get(ATTRIBUTION) or ""):
        choose_attribution(db, launch=launch, key=edit.attribution)
        changed = True
    stored_cap = (launch.answers or {}).get(FREQUENCY_CAP)
    if [edit.cap_times, edit.cap_days] != list(stored_cap or [None, None]):
        choose_frequency_cap(
            db, launch=launch, times=edit.cap_times, days=edit.cap_days
        )
        changed = True
    return changed
