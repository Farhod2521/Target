"""Who sits in a seat, across everything an owner's people do.

The rule: one person in one business takes one seat, whatever they do
there. A paid plan gives each page one free seat, which works only in that
page's business; the others sit in the seats bought, oldest first; the
rest wait, and may not work.

A sales manager's seat is the CRM's own answer (``crm.selectors.seating``),
which the cabinet's CRM and the bills already go by, and is never changed
here. Somebody who is not a manager - a targetolog - takes what that leaves:
the free seat of the business's page when no manager sits in it, else a
bought one.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.constants import LinkKind
from app.modules.businesses.models import BusinessLink, BusinessMember

FREE = "free"
PAID = "paid"
NONE = "none"


@dataclass(frozen=True, slots=True)
class Seats:
    """Every active member of the owner's businesses, seated or waiting."""

    free: int
    paid: int
    held: dict[uuid.UUID, str]
    waiting: tuple[uuid.UUID, ...]
    # The pages whose free seat nobody sits in, and the bought seats left.
    free_pages: frozenset[uuid.UUID]
    paid_left: int

    def kind_of(self, member_id: uuid.UUID) -> str:
        return self.held.get(member_id, NONE)

    def open_on(self, page_id: uuid.UUID | None) -> bool:
        """Whether one more person put to work on this page's business
        would sit."""
        return self.paid_left > 0 or (
            page_id is not None and page_id in self.free_pages
        )


def pages_of(db: Session, business_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """The page each business advertises from, whose free seat is its own."""
    if not business_ids:
        return {}
    return {
        business_id: page_id
        for business_id, page_id in db.execute(
            select(BusinessLink.business_id, BusinessLink.page_id).where(
                BusinessLink.business_id.in_(business_ids),
                BusinessLink.kind == LinkKind.META_PAIR,
                BusinessLink.unbound_at.is_(None),
                BusinessLink.page_id.is_not(None),
            )
        )
    }


def seats_of(db: Session, *, owner: User, at: datetime) -> Seats:
    from app.modules.crm.constants import SeatKind
    from app.modules.crm.models import CrmMember
    from app.modules.crm.selectors import seating
    from app.modules.integrations.selectors import enabled_pages

    crm = seating(db, owner=owner, at=at)
    members = list(
        db.scalars(
            select(BusinessMember)
            .where(
                BusinessMember.owner_id == owner.id,
                BusinessMember.is_active.is_(True),
            )
            .order_by(BusinessMember.joined_at, BusinessMember.id)
        )
    )
    pages = pages_of(db, [member.business_id for member in members])
    free_pages = (
        {page.id for page in enabled_pages(db, owner=owner)} if crm.free else set()
    )
    sat_free = [pk for pk, kind in crm.held.items() if kind == SeatKind.FREE]
    if sat_free:
        free_pages -= set(
            db.scalars(select(CrmMember.page_id).where(CrmMember.id.in_(sat_free)))
        )
    paid_left = max(0, crm.paid - crm.paid_used)
    held: dict[uuid.UUID, str] = {}
    waiting: list[uuid.UUID] = []
    for member in members:
        if member.crm_member_id is not None:
            kind = str(crm.kind_of(member.crm_member_id))
            if kind == NONE:
                waiting.append(member.id)
            else:
                held[member.id] = kind
    for member in members:
        if member.crm_member_id is not None:
            continue
        page = pages.get(member.business_id)
        if page is not None and page in free_pages:
            free_pages.discard(page)
            held[member.id] = FREE
        elif paid_left > 0:
            paid_left -= 1
            held[member.id] = PAID
        else:
            waiting.append(member.id)
    return Seats(
        free=crm.free,
        paid=crm.paid,
        held=held,
        waiting=tuple(waiting),
        free_pages=frozenset(free_pages),
        paid_left=paid_left,
    )


__all__ = ["FREE", "NONE", "PAID", "Seats", "pages_of", "seats_of"]
