"""What ``alembic revision --autogenerate`` may write against this database.

The database was built by the Django project and still carries what the
models never declare: Django's own tables (sessions, beat schedules,
permissions, its migration ledger) and every index and foreign key under the
name Django gave it. Compared as it is, autogenerate proposes dropping all of
that and creating it again under SQLAlchemy's names.

Two rules, applied to every generated revision:

- **Nothing is dropped.** A drop is written by hand, never generated.
- **Nothing that exists is created again.** An index, unique constraint or
  foreign key already in the database on the same columns is the same object
  under another name.

What was left out is logged, so a drop somebody meant is not lost silently.
"""

import logging
from typing import Any

from alembic.operations import ops
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

log = logging.getLogger("alembic.guard")

DROPS = (ops.DropTableOp, ops.DropColumnOp, ops.DropIndexOp, ops.DropConstraintOp)

Columns = tuple[str, ...]
Link = tuple[Columns, str]
Held = tuple[set[Columns], set[Columns], set[Link]]


def _columns(names: Any) -> Columns:
    return tuple(name for name in names if name is not None)


class Existing:
    """The column sets the database already indexes, constrains or links."""

    def __init__(self, bind: Connection) -> None:
        self._inspector = inspect(bind)
        self._tables = set(self._inspector.get_table_names())
        self._read: dict[str, Held] = {}

    def _table(self, name: str) -> Held:
        if name not in self._read:
            if name not in self._tables:
                self._read[name] = (set(), set(), set())
            else:
                indexes = self._inspector.get_indexes(name)
                uniques = self._inspector.get_unique_constraints(name)
                links = self._inspector.get_foreign_keys(name)
                self._read[name] = (
                    {_columns(row["column_names"]) for row in indexes},
                    {_columns(row["column_names"]) for row in uniques}
                    | {
                        _columns(row["column_names"])
                        for row in indexes
                        if row["unique"]
                    },
                    {
                        (tuple(row["constrained_columns"]), row["referred_table"])
                        for row in links
                    },
                )
        return self._read[name]

    def covers(self, op: Any) -> bool:
        if isinstance(op, ops.CreateIndexOp):
            index = op.to_index()
            columns = tuple(column.name for column in index.columns)
            if not columns or len(columns) != len(index.expressions):
                return False
            indexed, unique, _ = self._table(op.table_name)
            return columns in (unique if index.unique else indexed | unique)
        if isinstance(op, ops.CreateUniqueConstraintOp):
            return tuple(op.columns) in self._table(op.table_name)[1]
        if isinstance(op, ops.CreateForeignKeyOp):
            link = (tuple(op.local_cols), op.referent_table)
            return link in self._table(op.source_table)[2]
        return False


def _describe(op: Any) -> str:
    table = getattr(op, "table_name", "") or getattr(op, "source_table", "")
    name = (
        getattr(op, "index_name", None)
        or getattr(op, "constraint_name", None)
        or getattr(op, "column_name", None)
        or ""
    )
    return f"{type(op).__name__} {table} {name}".rstrip()


def _filtered(items: list[Any], existing: Existing, left_out: list[str]) -> list[Any]:
    kept = []
    for op in items:
        if isinstance(op, DROPS) or existing.covers(op):
            left_out.append(_describe(op))
            continue
        if isinstance(op, ops.OpContainer):
            op.ops = _filtered(op.ops, existing, left_out)
            if op.is_empty():
                continue
        kept.append(op)
    return kept


def guard(context: MigrationContext, revision: Any, directives: list[Any]) -> None:
    """``process_revision_directives`` for env.py: apply both rules."""
    script = directives[0]
    if context.bind is None or script.upgrade_ops.is_empty():
        return
    left_out: list[str] = []
    script.upgrade_ops.ops = _filtered(
        script.upgrade_ops.ops, Existing(context.bind), left_out
    )
    script.downgrade_ops = script.upgrade_ops.reverse()
    if left_out:
        log.warning(
            "Left out %d operation(s) on what the database already holds; "
            "write a drop by hand if one was meant:\n  %s",
            len(left_out),
            "\n  ".join(left_out),
        )
