"""What a plan bill renews beside the plan: the extra pages and the CRM
manager seats bought on the period that ends, less what the owner unticks.

The quote and the bill both count from here, so the price on the screen is
the price charged. Unticked pages and managers are let go only once the bill
is paid.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.billing.exceptions import (
    TooManyDropEmpty,
    TooManyDropPages,
    UnknownDropMember,
    UnknownDropPage,
)
from app.modules.billing.models import Subscription
from app.modules.billing.selectors.pages import paid_pages
from app.modules.billing.selectors.seats import paid_seats


@dataclass(frozen=True, slots=True)
class PageLine:
    id: uuid.UUID
    external_id: str
    name: str
    dropped: bool


@dataclass(frozen=True, slots=True)
class SeatLine:
    member_id: uuid.UUID
    name: str
    email: str
    page_id: uuid.UUID | None
    dropped: bool


@dataclass(frozen=True, slots=True)
class Renewal:
    """The extra pages and seats a plan bill carries into the next period."""

    pages_free: int
    pages_used: int
    pages_bought: int
    page_lines: tuple[PageLine, ...]
    empty_pages: int
    drop_empty: int
    seats_bought: int
    seat_lines: tuple[SeatLine, ...]

    @property
    def pages_paid_used(self) -> int:
        """Connected pages sitting in bought slots."""
        return self.pages_bought - self.empty_pages

    @property
    def drop_pages(self) -> tuple[uuid.UUID, ...]:
        return tuple(line.id for line in self.page_lines if line.dropped)

    @property
    def drop_members(self) -> tuple[uuid.UUID, ...]:
        return tuple(line.member_id for line in self.seat_lines if line.dropped)

    @property
    def pages_carried(self) -> int:
        kept = self.pages_paid_used - len(self.drop_pages)
        return max(0, min(self.pages_bought, kept + self.empty_pages - self.drop_empty))

    @property
    def seats_carried(self) -> int:
        kept = len(self.seat_lines) - len(self.drop_members)
        return max(0, min(self.seats_bought, kept))


NOTHING = Renewal(0, 0, 0, (), 0, 0, 0, ())


def renewal(
    db: Session,
    *,
    owner: User,
    subscription: Subscription | None,
    drop_pages: Iterable[str] = (),
    drop_members: Iterable[str] = (),
    drop_empty: int = 0,
) -> Renewal:
    """Count from the period ``subscription`` ends: the seats and pages bought
    and running at its last moment. Raises when a drop names what is not
    there to drop."""
    from app.modules.crm.selectors import paid_seat_takers
    from app.modules.integrations.selectors import enabled_pages, page_slots

    if subscription is None:
        return NOTHING
    last = subscription.expires_at - timedelta(seconds=1)
    bought = paid_pages(db, owner=owner, at=last)
    free = subscription.plan.included_pages + subscription.extra_pages
    used = page_slots(db, owner=owner).used
    paid_used = max(0, min(bought, used - free))
    empty = bought - paid_used

    unticked_pages = _ids(drop_pages, refusal=UnknownDropPage)
    pages = enabled_pages(db, owner=owner)
    if not unticked_pages <= {page.id for page in pages}:
        raise UnknownDropPage
    if len(unticked_pages) > paid_used:
        raise TooManyDropPages(limit=paid_used)
    if not 0 <= drop_empty <= empty:
        raise TooManyDropEmpty(limit=empty)
    page_lines = (
        tuple(
            PageLine(
                id=page.id,
                external_id=page.external_id,
                name=page.name or page.external_id,
                dropped=page.id in unticked_pages,
            )
            for page in pages
        )
        if paid_used
        else ()
    )

    seats = paid_seats(db, owner=owner, at=last)
    takers = paid_seat_takers(db, owner=owner, subscription=subscription)[:seats]
    unticked_members = _ids(drop_members, refusal=UnknownDropMember)
    if not unticked_members <= {member.id for member in takers}:
        raise UnknownDropMember
    seat_lines = tuple(
        SeatLine(
            member_id=member.id,
            name=member.user.full_name or member.user.email,
            email=member.user.email,
            page_id=member.page_id,
            dropped=member.id in unticked_members,
        )
        for member in takers
    )
    return Renewal(
        pages_free=free,
        pages_used=used,
        pages_bought=bought,
        page_lines=page_lines,
        empty_pages=empty,
        drop_empty=drop_empty,
        seats_bought=seats,
        seat_lines=seat_lines,
    )


def _ids(raw: Iterable[str], *, refusal: type[DomainError]) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    for value in raw:
        try:
            found.add(uuid.UUID(str(value)))
        except ValueError as exc:
            raise refusal() from exc
    return found
