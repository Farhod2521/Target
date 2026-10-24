from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.public.exceptions import DeletionRequestNotFound
from app.modules.public.models import DeletionRequest, Testimonial


def get_by_confirmation_code(db: Session, code: str) -> DeletionRequest:
    request = db.scalar(
        select(DeletionRequest).where(DeletionRequest.confirmation_code == code)
    )
    if request is None:
        raise DeletionRequestNotFound
    return request


def active_testimonials(db: Session) -> list[Testimonial]:
    return list(
        db.scalars(
            select(Testimonial)
            .where(Testimonial.is_active.is_(True))
            .order_by(Testimonial.sort_order, Testimonial.created_at)
        )
    )


__all__ = ["active_testimonials", "get_by_confirmation_code"]
