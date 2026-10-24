from collections.abc import Sequence
from dataclasses import dataclass

from metaads import PROVIDER
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount, PageInstagram


@dataclass(frozen=True, slots=True)
class Slots:
    allowed: int
    used: int
    MAX_MARKS = 10

    @property
    def free(self) -> int:
        return max(0, self.allowed - self.used)

    @property
    def has_room(self) -> bool:
        return self.free > 0

    @property
    def marks(self) -> tuple[bool, ...]:
        if self.allowed > self.MAX_MARKS or self.used > self.allowed:
            return ()
        return tuple(index < self.used for index in range(self.allowed))


def page_slots(db: Session, *, owner: User) -> Slots:
    from app.modules.billing.selectors import capacity

    pages = db.scalar(
        select(func.count())
        .select_from(PageAccount)
        .where(
            PageAccount.owner_id == owner.id,
            PageAccount.provider == PROVIDER,
            PageAccount.is_active.is_(True),
        )
    )
    return Slots(
        allowed=capacity(db, owner=owner).pages,
        used=int(pages or 0) + extra_instagram_count(db, owner=owner),
    )


def extra_instagram_count(db: Session, *, owner: User) -> int:
    page = aliased(PageAccount)
    return int(
        db.scalar(
            select(func.count())
            .select_from(PageInstagram)
            .join(page, page.id == PageInstagram.page_id)
            .where(
                PageInstagram.owner_id == owner.id,
                PageInstagram.is_active.is_(True),
                page.is_active.is_(True),
                page.provider == PROVIDER,
                PageInstagram.instagram_user_id != page.instagram_user_id,
            )
        )
        or 0
    )


def enabled_ad_accounts(db: Session, *, owner: User) -> list[AdAccount]:
    return list(
        db.scalars(
            select(AdAccount)
            .where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == PROVIDER,
                AdAccount.is_active.is_(True),
            )
            .order_by(AdAccount.is_current.desc(), AdAccount.name)
        )
    )


def enabled_pages(db: Session, *, owner: User) -> list[PageAccount]:
    return list(
        db.scalars(
            select(PageAccount)
            .where(
                PageAccount.owner_id == owner.id,
                PageAccount.provider == PROVIDER,
                PageAccount.is_active.is_(True),
            )
            .order_by(PageAccount.is_current.desc(), PageAccount.name)
        )
    )


def page_shown(pages: Sequence[PageAccount]) -> PageAccount | None:
    if pages and pages[0].is_current:
        return pages[0]
    return pages[0] if len(pages) == 1 else None
