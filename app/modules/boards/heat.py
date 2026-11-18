"""How warm a lead is: what the client did after signing up, as a Sales
manager wants to know before the call. The same points order «Lid olish»,
so the warmest waiting lead is given first."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from metaads import PROVIDER
from sqlalchemy import Integer, and_, case, exists, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice
from app.modules.boards.constants import (
    HEAT_BILL,
    HEAT_BUSINESS,
    HEAT_FACEBOOK,
    HEAT_HOT,
    HEAT_LABELS,
    HEAT_PAGE,
    HEAT_RETURN_MINUTES,
    HEAT_RETURNED,
    Heat,
)


@dataclass(frozen=True, slots=True)
class Signals:
    bill: bool = False
    facebook: bool = False
    page: bool = False
    business: bool = False
    returned: bool = False

    @property
    def points(self) -> int:
        return (
            HEAT_BILL * self.bill
            + HEAT_FACEBOOK * self.facebook
            + HEAT_PAGE * self.page
            + HEAT_BUSINESS * self.business
            + HEAT_RETURNED * self.returned
        )

    @property
    def heat(self) -> Heat:
        if self.points >= HEAT_HOT:
            return Heat.HOT
        return Heat.WARM if self.points else Heat.COLD

    def out(self) -> dict[str, Any]:
        return {
            "level": str(self.heat),
            "label": str(HEAT_LABELS[self.heat]),
            "points": self.points,
            "bill": self.bill,
            "facebook": self.facebook,
            "page": self.page,
            "business": self.business,
            "returned": self.returned,
        }


def _bill_open(owner: Any, now: datetime) -> Any:
    return exists().where(
        Invoice.owner_id == owner,
        Invoice.kind == str(InvoiceKind.PLAN),
        or_(
            and_(
                Invoice.status == str(InvoiceStatus.PENDING), Invoice.expires_at > now
            ),
            Invoice.status == str(InvoiceStatus.HELD),
        ),
    )


def _facebook(owner: Any) -> Any:
    from app.modules.integrations.models import ProviderConnection

    return exists().where(
        ProviderConnection.owner_id == owner, ProviderConnection.provider == PROVIDER
    )


def _page(owner: Any) -> Any:
    from app.modules.integrations.models import PageAccount

    return exists().where(
        PageAccount.owner_id == owner, PageAccount.is_active.is_(True)
    )


def _business(owner: Any) -> Any:
    from app.modules.businesses.models import Business

    return exists().where(Business.user_id == owner)


def _returned(user: Any = User) -> Any:
    return user.last_login > user.date_joined + timedelta(minutes=HEAT_RETURN_MINUTES)


def points_sql(owner: Any, *, now: datetime, user: Any = User) -> Any:
    """The points as an SQL expression over a client's id (``owner``) whose
    ``users`` row is joined as ``user``: the order «Lid olish» gives leads in."""

    def weigh(test: Any, weight: int) -> Any:
        return case((test, weight), else_=0).cast(Integer)

    return (
        weigh(_bill_open(owner, now), HEAT_BILL)
        + weigh(_facebook(owner), HEAT_FACEBOOK)
        + weigh(_page(owner), HEAT_PAGE)
        + weigh(_business(owner), HEAT_BUSINESS)
        + weigh(_returned(user), HEAT_RETURNED)
    )


def signals_for(
    db: Session, owner_ids: list[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, Signals]:
    """Each client's signals, in one query."""
    if not owner_ids:
        return {}
    rows = db.execute(
        select(
            User.id,
            _bill_open(User.id, now),
            _facebook(User.id),
            _page(User.id),
            _business(User.id),
            case((_returned(), True), else_=False),
        ).where(User.id.in_(set(owner_ids)))
    )
    return {
        owner: Signals(
            bill=bool(bill),
            facebook=bool(facebook),
            page=bool(page),
            business=bool(business),
            returned=bool(returned),
        )
        for owner, bill, facebook, page, business, returned in rows
    }
