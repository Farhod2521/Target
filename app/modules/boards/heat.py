"""What a client did after signing up, as points that order «Lid olish»:
the most active waiting lead is given first. Not shown to anyone."""

from datetime import datetime, timedelta
from typing import Any

from metaads import PROVIDER
from sqlalchemy import Integer, and_, case, exists, or_

from app.modules.accounts.models import User
from app.modules.billing.constants import InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice
from app.modules.boards.constants import (
    HEAT_BILL,
    HEAT_BUSINESS,
    HEAT_FACEBOOK,
    HEAT_PAGE,
    HEAT_RETURN_MINUTES,
    HEAT_RETURNED,
)


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
