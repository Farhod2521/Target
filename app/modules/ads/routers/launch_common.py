"""What every launch route shares: the launch, the gate, and the answer.

Reading is open to the owner; a write first checks the owner may still
prepare campaigns, as the Django wizard's ``LaunchMixin`` did.
"""

import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError, NotFound
from app.modules.accounts.models import User
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.launches import launch_for, resume_step
from app.modules.businesses.models import Business
from app.modules.businesses.selectors import business_for_page

T = TypeVar("T")
NO_PROFILE = "Avval biznes profilini to'ldiring."


def owned_launch(db: Session, *, user: User, launch_id: uuid.UUID) -> CampaignLaunch:
    """The owner's launch, or 404 - never somebody else's."""
    launch = launch_for(db, owner=user, launch_id=launch_id)
    if launch is None:
        raise NotFound("Tayyorlash topilmadi.")
    return launch


def writable_launch(db: Session, *, user: User, launch_id: uuid.UUID) -> CampaignLaunch:
    """The owner's launch, once the owner may still prepare one."""
    from app.modules.billing.services import require_preparation

    launch = owned_launch(db, user=user, launch_id=launch_id)
    require_preparation(db, owner=user)
    return launch


def launch_business(db: Session, *, launch: CampaignLaunch) -> Business:
    """The business behind the launch's page, or a refusal naming the fix."""
    business = business_for_page(db, owner=launch.owner, page=launch.page)
    if business is None:
        raise DomainError(NO_PROFILE)
    return business


def committed[T](db: Session, run: Callable[[], T]) -> T:
    """Run a write and commit it; a refusal rolls everything back."""
    try:
        result = run()
    except DomainError:
        db.rollback()
        raise
    db.commit()
    return result


def attempted(db: Session, run: Callable[[], object]) -> str:
    """Like :func:`committed`, but a refusal is answered as a sentence."""
    try:
        run()
    except DomainError as exc:
        db.rollback()
        return exc.message
    db.commit()
    return ""


def launch_head(launch: CampaignLaunch) -> dict[str, Any]:
    """The few facts every answer about a launch carries."""
    return {
        "id": str(launch.id),
        "provider": launch.provider,
        "status": launch.status,
        "step": launch.step,
        "progress": launch.progress,
        "currency": launch.currency,
        "daily_budget_minor": launch.daily_budget_minor,
        "start_date": launch.start_date,
        "end_date": launch.end_date,
        "resume": resume_step(launch),
        "created_at": launch.created_at,
        "updated_at": launch.updated_at,
    }


def encoded(value: Any) -> Any:
    """Dataclasses, enums and dates as JSON, the way FastAPI would."""
    return jsonable_encoder(value)


__all__ = [
    "attempted",
    "committed",
    "encoded",
    "launch_business",
    "launch_head",
    "owned_launch",
    "writable_launch",
]
