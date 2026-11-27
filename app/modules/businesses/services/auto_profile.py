"""A business's profile made by us, the moment its page is paired.

Preparation used to stop on a form: name, kind, city. Nobody is asked any
more. The profile is written from what the page already says - its name,
its city, its Instagram's website - with the catalogue's general kind as a
placeholder, and a worker then reads the page and guesses the real kind
(``services.guess``). What it guesses stays a guess until somebody of the
business says yes, in a chat or on the business's own page.

A profile somebody filled in by hand is never touched here.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import on_commit
from app.common.presets import fallback_category
from app.modules.audit.constants import EventName
from app.modules.audit.services.emit import emit
from app.modules.businesses.models import Business
from app.modules.integrations.models import PageAccount

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Tashkent"
NAME_CHARS = 255
WEBSITE_CHARS = 200
GUESS_AFTER_SECONDS = 90


def ensure_profile(
    db: Session, *, owner_id: uuid.UUID, page: PageAccount
) -> Business | None:
    """The page's profile, made if nobody wrote one; flushes. Answers the
    new row, or nothing when the page already had a profile."""
    held = db.scalar(
        select(Business.id).where(
            Business.user_id == owner_id, Business.page_id == page.id
        )
    )
    if held is not None:
        return None
    defaults = settings.profile_defaults
    website = str(page.instagram_website or "")
    business = Business(
        user_id=owner_id,
        page_id=page.id,
        name=str(page.name or page.instagram_name or "")[:NAME_CHARS],
        category=fallback_category(),
        timezone=defaults.get("timezone") or DEFAULT_TIMEZONE,
        country_code=defaults.get("country_code", ""),
        city=str(page.location_city or ""),
        website=website if len(website) <= WEBSITE_CHARS else "",
    )
    if page.has_pin:
        business.lat, business.lng = page.location_lat, page.location_lng
    db.add(business)
    db.flush()
    emit(
        db,
        owner_id=owner_id,
        name=EventName.BUSINESS_CREATED,
        aggregate_type="business",
        aggregate_id=business.id,
        payload={
            "name": business.name,
            "country_code": business.country_code,
            "timezone": business.timezone,
            "page": str(page.id),
            "ad_account": "",
            "auto": True,
        },
    )
    business_id = str(business.id)
    on_commit(db, lambda: _queue_guess(business_id))
    logger.info("profile %s made for page %s", business.id, page.id)
    return business


def _queue_guess(business_id: str) -> None:
    """Hand the new profile to the worker that guesses its kind. A broker
    that is down loses a guess, never the commit that made the profile."""
    from app.modules.businesses.tasks import guess_business_kind_task

    try:
        # A little later: the page's Instagram is being read right now, and
        # its bio says more about the business than its name does.
        guess_business_kind_task.apply_async(
            (business_id,), countdown=GUESS_AFTER_SECONDS
        )
    except Exception:
        logger.exception("kind guess not queued", extra={"business": business_id})


__all__ = ["ensure_profile"]
