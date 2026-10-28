"""Deleting rows the way Django did.

Django ran ``on_delete`` in Python, so the copied database's foreign keys are
NO ACTION and checked only at commit: a delete that forgets the rows pointing
at it fails there, after any ``except IntegrityError`` has been left behind.
The models still carry Django's rules as ``ondelete``; this applies them first.
"""

from functools import cache

from sqlalchemy import ColumnElement, Table, delete, exists, select, update
from sqlalchemy.orm import Session

from app.common.db import Base


class ProtectedRows(Exception):
    """A row to delete is still referred to through a PROTECT foreign key."""

    def __init__(self, table: str) -> None:
        super().__init__(f"{table} still refers to the rows")
        self.table = table


@cache
def _incoming(name: str) -> tuple[tuple[Table, str, str | None], ...]:
    return tuple(
        (child, fk.parent.name, fk.ondelete)
        for child in Base.metadata.sorted_tables
        for fk in child.foreign_keys
        if fk.column.table.name == name
    )


def delete_rows(db: Session, table: Table, where: ColumnElement[bool]) -> int:
    """Delete the matching rows, nulling and cascading as Django would.

    Raises :class:`ProtectedRows` with nothing changed.
    """
    with db.begin_nested():
        return _delete(db, table, where)


def _delete(db: Session, table: Table, where: ColumnElement[bool]) -> int:
    incoming = _incoming(table.name)
    if incoming:
        keys = list(db.scalars(select(table.c.id).where(where)))
        if not keys:
            return 0
        where = table.c.id.in_(keys)
        protected = []
        for child, column, rule in incoming:
            pointing = child.c[column].in_(keys)
            if rule == "SET NULL":
                db.execute(update(child).where(pointing).values({column: None}))
            elif rule == "CASCADE":
                _delete(db, child, pointing)
            elif rule == "RESTRICT":
                protected.append((child, pointing))
        for child, pointing in protected:
            if db.scalar(select(exists().where(pointing))):
                raise ProtectedRows(child.name)
    return db.execute(delete(table).where(where)).rowcount
