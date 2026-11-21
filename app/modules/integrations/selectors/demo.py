"""The showcase account: a customer whose Meta side is made up.

Its connection carries ``ConnectionStatus.DEMO``. Every place that asks a
connection for a token refuses that status as it refuses a dead one, so
nothing is ever sent to the network for it; every screen reads it as
connected. What is left to say here is who these owners are - for the jobs
that judge an account by its figures, and for the office's own counts,
which a made-up customer must not move.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.orm import Session

from app.modules.integrations.constants import ConnectionStatus
from app.modules.integrations.models import AdAccount, PageAccount, ProviderConnection


def demo_owner_ids() -> Select[Any]:
    """Whose account is a showcase, as a query to narrow another with."""
    return select(ProviderConnection.owner_id).where(
        ProviderConnection.status == ConnectionStatus.DEMO
    )


def not_demo(owner: Any) -> ColumnElement[bool]:
    """Rows of everybody but the showcase accounts; ``owner`` is the column
    holding the owner's id. A row with no owner - a deleted account's
    receipt - stays."""
    return or_(owner.is_(None), owner.not_in(demo_owner_ids()))


def demo_owners(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(demo_owner_ids()))


def is_demo_owner(db: Session, *, owner_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(ProviderConnection.id)
            .where(
                ProviderConnection.owner_id == owner_id,
                ProviderConnection.status == ConnectionStatus.DEMO,
            )
            .limit(1)
        )
        is not None
    )


def is_demo_account(account: AdAccount | None) -> bool:
    connection = account.connection if account is not None else None
    return connection is not None and connection.status == ConnectionStatus.DEMO


def is_demo_page(page: PageAccount | None) -> bool:
    connection = page.connection if page is not None else None
    return connection is not None and connection.status == ConnectionStatus.DEMO
