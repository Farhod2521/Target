"""What one creation attempt sent, as a value that can be compared."""

import hashlib
import json
from typing import Any, Final

from sqlalchemy.orm import Session

from app.modules.ads.constants import UNCHANGED_REFUSALS
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.goals import goal_optimization
from app.modules.ads.selectors.variants import launch_variants
from app.modules.businesses.models import Business
from core.targeting import accepts_cap

SENT_KEY: Final = "sent"


def reaches_nobody(*, launch: CampaignLaunch) -> bool:
    """Whether the stored estimate says nobody would see this advert."""
    return launch.estimated_at is not None and launch.audience_upper == 0


def cap_not_sent(db: Session, *, launch: CampaignLaunch) -> bool:
    """A ceiling is stored and the kind it would ride on takes none."""
    if not launch.max_result_cost_minor:
        return False
    return not accepts_cap(goal_optimization(db, launch=launch))


def attempt_fingerprint(
    db: Session, *, launch: CampaignLaunch, business: Business, preset_version: str
) -> str:
    """One hash of everything a creation attempt is built from."""
    page = launch.page
    payload: dict[str, Any] = {
        "answers": launch.answers,
        "draft": launch.draft,
        "budget": launch.daily_budget_minor,
        "cost_cap": None
        if cap_not_sent(db, launch=launch)
        else launch.max_result_cost_minor,
        "start": launch.start_date,
        "quality": launch.buy_qualified_leads,
        "form": launch.lead_form_external_id,
        "page": [launch.page_id, page.updated_at if page is not None else None],
        "business": [business.id, business.updated_at],
        "preset": preset_version,
        "variants": [
            [
                variant.position,
                variant.media_asset_id,
                variant.media_upload or "",
                variant.library_upload,
                variant.brief,
                variant.primary_text,
                variant.headline,
                variant.description,
            ]
            for variant in launch_variants(db, launch=launch)
        ],
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def repeats_refusal(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business | None,
    preset_version: str,
) -> bool:
    """Whether pressing now would send exactly what was just refused."""
    if launch.error_code not in UNCHANGED_REFUSALS or business is None:
        return False
    detail = launch.error_detail if isinstance(launch.error_detail, dict) else {}
    sent = detail.get(SENT_KEY)
    if not sent:
        return False
    return bool(
        sent
        == attempt_fingerprint(
            db, launch=launch, business=business, preset_version=preset_version
        )
    )
