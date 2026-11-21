"""Taking the showcase account away - see the package's own note."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import Base
from app.common.deletion import delete_rows
from app.modules.accounts.constants import PURGE_ORDER
from app.modules.accounts.models import User
from app.modules.accounts.services.members import model_by_label, purge_owned_rows
from app.modules.integrations.selectors.demo import is_demo_owner


class NotADemo(Exception):
    """The account asked for is not one ``seed`` wrote: it is left alone."""


def _left_behind(db: Session, *, user: User) -> dict[str, int]:
    """Rows that hold on to the account and that the purge order does not
    name - an alert the guard wrote, say. They would stop the delete."""
    models = model_by_label()
    covered = {models[label].__tablename__ for label in PURGE_ORDER if label in models}
    gone: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in covered or table.name == "users":
            continue
        for key in table.foreign_keys:
            if key.column.table.name != "users" or key.ondelete != "RESTRICT":
                continue
            rows = delete_rows(db, table, table.c[key.parent.name] == user.id)
            if rows:
                gone[table.name] = gone.get(table.name, 0) + rows
    return gone


def wipe(db: Session, *, email: str) -> dict[str, int]:
    """Delete the showcase account under ``email``: its managers' logins,
    every row it owns, then itself. How many rows went, by table.

    Only an account whose Meta connection carries the showcase mark is
    touched - a customer's, a colleague's or a mistyped address raises
    :class:`NotADemo` with nothing changed. The bills go too: they were
    never money, so no receipt of them is kept. The caller commits.
    """
    address = email.strip().lower()
    owner = db.scalar(select(User).where(func.lower(User.email) == address))
    if owner is None:
        raise NotADemo(f"{address}: bunday akkaunt yo'q")
    if owner.is_staff or owner.is_superuser or owner.crm_owner_id is not None:
        raise NotADemo(f"{address}: bu namoyish akkaunti emas")
    if not is_demo_owner(db, owner_id=owner.id):
        raise NotADemo(f"{address}: bu namoyish akkaunti emas, tegilmadi")
    gone: dict[str, int] = {}

    def count(rows: dict[str, int]) -> None:
        for label, number in rows.items():
            gone[label] = gone.get(label, 0) + number

    logins = list(db.scalars(select(User).where(User.crm_owner_id == owner.id)))
    for person in (*logins, owner):
        count(_left_behind(db, user=person))
        count(purge_owned_rows(db, user=person))
    for login in logins:
        delete_rows(db, User.__table__, User.id == login.id)
    delete_rows(db, User.__table__, User.id == owner.id)
    gone["accounts.User"] = len(logins) + 1
    return gone
