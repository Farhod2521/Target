"""One customer's advertising, as JSON: the list, one advert whole, its preview.

Support, Finance and Owner only. The customer is in the address so that a
launch id read off another customer's page answers 404.
"""

import uuid
from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import Db
from app.common.timezone import localtime
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    MAX_PREVIEW_POLLS,
    PREVIEW_AD_FORMAT,
    PREVIEW_POLL_SECONDS,
)
from app.modules.ads.selectors import fresh_preview
from app.modules.ads.selectors.launch_live import LiveForm, launch_ads
from app.modules.ads.selectors.launch_settings import AudienceLines, LaunchSettings
from app.modules.backoffice.constants import ADMIN_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import amounts, choices
from app.modules.backoffice.schemas import AdFrameOut, CustomerAdOut, CustomerAdsOut
from app.modules.backoffice.selectors.ad_reading import (
    UNITS,
    AdLine,
    AdReading,
    GroupLine,
    ad_reading,
    owned_launch,
)
from app.modules.backoffice.selectors.advertising import (
    DEFAULT_PERIOD,
    PERIODS,
    AdRow,
    AdWindow,
    advertising,
    asked_window,
)
from app.modules.backoffice.selectors.card import person
from app.modules.metrics.selectors.panel import FigureSums

router = APIRouter(prefix="/customers/{customer_id}/ads")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]

PERIOD_Q = Query(DEFAULT_PERIOD, description="A value from `periods`.")
SINCE_Q = Query(None, description="`range`: the first day, YYYY-MM-DD.")
UNTIL_Q = Query(None, description="`range`: the last day, YYYY-MM-DD.")


def _owner(db: Db, customer_id: uuid.UUID) -> User:
    owner = person(db, customer_id=customer_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return owner


def _window(*, period: str, since: date | None, until: date | None) -> AdWindow:
    return asked_window(period=period, since=since, until=until, now=localtime())


def window_out(window: AdWindow) -> dict[str, Any]:
    return {
        "period": window.period,
        "since": window.since,
        "until": window.until,
        "refused": window.refused,
        "periods": choices(PERIODS),
    }


def row_out(row: AdRow) -> dict[str, Any]:
    return {
        "launch_id": str(row.launch_id),
        "campaign_external_id": row.campaign_external_id,
        "campaign_name": row.campaign_name,
        "started_at": row.started_at,
        "goal": row.goal,
        "page": row.page,
        "delivery_label": row.delivery_label,
        "is_running": row.is_running,
        "spend_minor": row.spend_minor,
        "currency": row.currency,
        "results": row.results,
        "result_word": row.result_word,
        "result_cost_minor": row.result_cost_minor,
        "result_cost_label": row.result_cost_label,
        "note": row.note,
        "impressions": row.impressions,
        "reach": row.reach,
        "clicks": row.clicks,
        "link_clicks": row.link_clicks,
        "leads": row.leads,
        "ctr_percent": row.ctr_percent,
        "cpm_minor": row.cpm_minor,
        "cpc_minor": row.cpc_minor,
    }


def sums_out(sums: FigureSums) -> dict[str, Any]:
    return {
        **asdict(sums),
        "ctr_percent": sums.ctr_percent,
        "cpm_minor": sums.cpm_minor,
        "cpc_minor": sums.cpc_minor,
    }


def audience_out(lines: AudienceLines | None) -> dict[str, Any] | None:
    if lines is None:
        return None
    return {
        "places": list(lines.places),
        "excluded_places": list(lines.excluded_places),
        "ages": lines.ages,
        "genders": lines.genders,
        "interests": [list(block) for block in lines.interests],
        "excluded_interests": list(lines.excluded_interests),
        "placements": list(lines.placements),
        "devices": list(lines.devices),
        "own_lists": list(lines.own_lists),
        "excluded_lists": list(lines.excluded_lists),
        "is_automatic": lines.is_automatic,
    }


def settings_out(found: LaunchSettings) -> dict[str, Any]:
    cap = found.frequency_cap
    return {
        "goal": found.goal,
        "goal_text": found.goal_text,
        "offer_text": found.offer_text,
        "link_url": found.link_url,
        "phone": found.phone,
        "campaign_name": found.campaign_name,
        "created_at": found.created_at,
        "page": found.page,
        "currency": found.currency,
        "daily_budget_minor": found.daily_budget_minor,
        "daily_min_minor": found.daily_min_minor,
        "daily_max_minor": found.daily_max_minor,
        "total_cap_minor": found.total_cap_minor,
        "max_result_cost_minor": found.max_result_cost_minor,
        "start_date": found.start_date,
        "end_date": found.end_date,
        "audience_lower": found.audience_lower,
        "audience_upper": found.audience_upper,
        "audience": audience_out(found.audience),
        "button": found.button,
        "conversion_event": found.conversion_event,
        "url_tags": found.url_tags,
        "attribution": found.attribution,
        "frequency_cap": {"times": cap[0], "days": cap[1]} if cap else None,
        "buys_qualified_leads": found.buys_qualified_leads,
        "decisions": [
            {
                "key": row.key,
                "label": row.label,
                "value": row.value,
                "by": row.by,
                "by_label": row.by_label,
            }
            for row in found.decisions
        ],
        "ads": [
            {
                "id": str(ad.id),
                "position": ad.position,
                "name": ad.name,
                "headline": ad.headline,
                "text": ad.text,
                "description": ad.description,
                "words_by": ad.words_by,
                "words_by_label": ad.words_by_label,
                "picture": ad.picture,
                "is_video": ad.is_video,
                "video_url": ad.video_url,
                "media_kind_label": ad.media_kind_label,
                "post_url": ad.post_url,
            }
            for ad in found.ads
        ],
    }


def form_out(form: LiveForm) -> dict[str, Any]:
    card = form.card
    return {
        "external_id": form.external_id,
        "is_synced": card is not None,
        "name": card.name if card is not None else "",
        "questions": list(card.questions) if card is not None else [],
        "custom_questions": list(card.custom_questions) if card is not None else [],
        "leads_count": card.leads_count if card is not None else None,
        "collecting": form.collecting,
        "privacy_url": form.privacy_url,
        "locale": form.locale,
    }


def live_out(found: AdReading) -> dict[str, Any]:
    live = found.live
    return {
        "status": live.status,
        "step": live.step,
        "error": live.error,
        "delivery_note": live.delivery_note,
        "qualified": live.qualified,
        "ads": [
            {
                "external_id": ad.external_id,
                "name": ad.name,
                "delivery": ad.delivery,
                "delivery_label": ad.delivery_label,
                "problem": ad.problem,
                "picture": ad.picture,
                "is_video": ad.is_video,
                "video_url": ad.video_url,
                "text": ad.text,
                "headline": ad.headline,
                "description": ad.description,
                "link": ad.link,
                "button": ad.button,
                "post": (
                    {
                        "external_id": ad.post.external_id,
                        "url": ad.post.url,
                        "kind_label": ad.post.kind_label,
                        "text": ad.post.text,
                        "picture": ad.post.picture,
                    }
                    if ad.post is not None
                    else None
                ),
            }
            for ad in live.ads
        ],
        "forms": [form_out(form) for form in live.forms],
    }


def line_out(line: AdLine) -> dict[str, Any]:
    return {
        "external_id": line.external_id,
        "name": line.name,
        "delivery_label": line.delivery_label,
        "quality_ranking": line.quality_ranking,
        "sums": sums_out(line.sums),
        "leads": line.leads,
        "lead_cost_minor": line.lead_cost_minor,
    }


def group_out(group: GroupLine) -> dict[str, Any]:
    return {
        "external_id": group.external_id,
        "name": group.name,
        "delivery_label": group.delivery_label,
        "optimization_goal": group.optimization_goal,
        "daily_budget_minor": group.daily_budget_minor,
        "is_learning": group.is_learning,
        "problem": group.problem,
        "audience": audience_out(group.audience),
        "sums": sums_out(group.sums),
        "leads": group.leads,
        "lead_cost_minor": group.lead_cost_minor,
        "ads": [line_out(line) for line in group.ads],
    }


def figures_out(found: AdReading) -> dict[str, Any] | None:
    figures, result, lifetime = found.figures, found.result, found.lifetime
    if figures is None or result is None or lifetime is None:
        return None
    return {
        "sums": sums_out(figures.total),
        "reach": found.reach,
        "reach_is_exact": found.reach_is_exact,
        "result": {
            "label": result.label,
            "count": result.count,
            "cost_minor": result.cost_minor,
            "cost_label": result.cost_label,
            "note": result.note,
        },
        "leads": found.leads,
        "qualified": found.qualified,
        "synced_at": figures.synced_at,
        "lifetime_leads": {
            "total": lifetime.total,
            "tests": lifetime.tests,
            "organic": lifetime.organic,
            "first_at": lifetime.first_at,
            "last_at": lifetime.last_at,
        },
    }


def campaign_out(found: AdReading) -> dict[str, Any] | None:
    row, campaign = found.row, found.campaign
    if campaign is None or row is None:
        return None
    return {
        "external_id": campaign.external_id,
        "name": campaign.name,
        "objective": campaign.objective_raw,
        "delivery_label": row.delivery_label,
        "is_running": row.is_running,
        "daily_budget_minor": campaign.daily_budget_minor,
        "spend_cap_minor": campaign.spend_cap_minor,
        "currency": campaign.currency,
        "created_at": campaign.created_time,
        "problem": campaign.issue_summary,
    }


@router.get("", responses={200: {"model": CustomerAdsOut}})
def customer_ads(
    customer_id: uuid.UUID,
    db: Db,
    user: Admin,
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
) -> dict[str, Any]:
    """Every advert this product launched for the account, over one window.

    Only rows that spent, produced or still deliver, except for `all`.
    """
    owner = _owner(db, customer_id)
    found = advertising(
        db, owner=owner, window=_window(period=period, since=since, until=until)
    )
    return {
        "period": found.window.period,
        "periods": choices(PERIODS),
        "window": window_out(found.window),
        "running": found.running,
        "totals": amounts(found.totals),
        "summary": [
            {
                "currency": row.currency,
                "spend_minor": row.spend_minor,
                "impressions": row.impressions,
                "clicks": row.clicks,
                "link_clicks": row.link_clicks,
                "leads": row.leads,
                "ctr_percent": row.ctr_percent,
                "cpm_minor": row.cpm_minor,
                "cpc_minor": row.cpc_minor,
                "lead_cost_minor": row.lead_cost_minor,
            }
            for row in found.summary
        ],
        "hidden": found.hidden,
        "rows": [row_out(row) for row in found.rows],
    }


@router.get("/{launch_id}", responses={200: {"model": CustomerAdOut}})
def customer_ad(
    customer_id: uuid.UUID,
    launch_id: uuid.UUID,
    db: Db,
    user: Admin,
    period: str = PERIOD_Q,
    since: date | None = SINCE_Q,
    until: date | None = UNTIL_Q,
    bar: str = Query("", description="`day`, `week`, `month`; empty fits the window."),
) -> dict[str, Any]:
    """One advert whole: its figures, how it was set up, and what runs now."""
    owner = _owner(db, customer_id)
    launch = owned_launch(db, owner=owner, launch_id=launch_id)
    if launch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    found = ad_reading(
        db,
        owner=owner,
        launch=launch,
        window=_window(period=period, since=since, until=until),
        by=bar,
    )
    return {
        "launch_id": str(launch.id),
        "window": window_out(found.window),
        "bar": found.unit,
        "bars_offered": choices(UNITS),
        "row": row_out(found.row) if found.row is not None else None,
        "campaign": campaign_out(found),
        "figures": figures_out(found),
        "bars": [
            {
                "key": row.key,
                "label": row.label,
                "hint": row.hint,
                "sums": sums_out(row.sums),
                "reach": row.reach,
                "leads": row.leads,
                "qualified": row.qualified,
                "results": row.results,
                "result_cost_minor": row.result_cost_minor,
            }
            for row in found.bars
        ],
        "groups": [group_out(group) for group in found.groups],
        "siblings": [
            {"launch_id": str(row.launch_id), "started_at": row.started_at}
            for row in found.siblings
        ],
        "settings": settings_out(found.settings),
        "live": live_out(found),
    }


@router.get("/{launch_id}/preview/{ad_id}", responses={200: {"model": AdFrameOut}})
def customer_ad_preview(
    customer_id: uuid.UUID,
    launch_id: uuid.UUID,
    ad_id: str,
    db: Db,
    user: Admin,
    tries: int = Query(0, ge=0, description="`tries` from the last answer."),
) -> dict[str, Any]:
    """Meta's own frame of one advert this launch put on the provider.

    The first ask queues the fetch on the customer's connection; ask again
    with `tries` while `polling` is true.
    """
    owner = _owner(db, customer_id)
    launch = owned_launch(db, owner=owner, launch_id=launch_id)
    if launch is None or ad_id not in {
        ad.external_id for ad in launch_ads(db, launch=launch)
    }:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    frame = fresh_preview(db, owner=owner, external_id=ad_id)
    polling = frame is None and tries < MAX_PREVIEW_POLLS
    if frame is None and tries == 0:
        from app.modules.ads.tasks import fetch_preview_task

        fetch_preview_task.delay(str(owner.id), ad_id, PREVIEW_AD_FORMAT)
    return {
        "src": frame.src if frame is not None else "",
        "width": frame.width if frame is not None else 0,
        "height": frame.height if frame is not None else 0,
        "polling": polling,
        "tries": tries + 1,
        "poll_seconds": PREVIEW_POLL_SECONDS,
        "gave_up": frame is None and not polling,
    }
