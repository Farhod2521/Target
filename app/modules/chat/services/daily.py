"""Who the business is, for the system prompt of the weekly reading.

The daily message is figures only and no model reads the day, so the one
piece left here is the business line the week's reading still uses.
"""

from sqlalchemy.orm import Session

from app.common.i18n import get_language
from app.modules.accounts.models import User


def about(db: Session, owner: User, *, page_id: str) -> str:
    """The language to answer in, and who the business is. Nothing else."""
    from app.modules.businesses.selectors import business_for_page_id, category_label

    lines = [f"Answer in: {get_language() or owner.language}"]
    business = business_for_page_id(db, owner=owner, page_id=page_id)
    if business is not None:
        trade = category_label(business)
        lines += [
            "",
            "## The business",
            f"- Nomi: {business.name}",
            f"- Sohasi: {trade}",
            f"- Nima sotadi: {business.offer_text or trade}",
        ]
    return "\n".join(lines)


__all__ = ["about"]
